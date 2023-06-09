from pymongo import MongoClient
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import hashlib
import datetime
import jwt
import time
from pytz import timezone
from chatgpt import *
import bson
import threading
from tqdm import tqdm

client = MongoClient('localhost', 27017)
db = client.dbjungle

app = Flask(__name__)
SECRET_KEY = 'CRAFTON_AEIOU_5TEAM'
app.secret_key = SECRET_KEY


@app.route('/')
def home():
    if 'Authorization' in session:
        token_receive = session['Authorization']
        try:
            payload = jwt.decode(token_receive, SECRET_KEY,
                                 algorithms=['HS256'])
            user_info = db.user.find_one({"id": payload['id']})
            return render_template('index.html', isLogin=True, nickname=user_info["nick"])
        except jwt.ExpiredSignatureError:
            session.pop('Authorization', None)
            return redirect(url_for("redirectPage", alert="로그인 시간이 만료되었습니다. 다시 로그인 해주세요."))
        except jwt.exceptions.DecodeError:
            session.pop('Authorization', None)
            return redirect(url_for("redirectPage", alert="로그인 정보가 존재하지 않아 로그아웃 되었습니다."))
    else:
        return render_template('index.html')


@app.route('/join')
def join():
    if 'Authorization' in session:
        return redirect(url_for("home"))
    return render_template('join.html')


@app.route('/login')
def login():
    if 'Authorization' in session:
        return redirect(url_for("home"))
    return render_template('login.html')


@app.route('/api/login', methods=['POST'])
def api_login():
    id_receive = request.form['id_give']
    pw_receive = request.form['pw_give']
    pw_hash = hashlib.sha256(pw_receive.encode('utf-8')).hexdigest()
    result = db.user.find_one({'id': id_receive, 'pw': pw_hash})

    if result is not None:
        payload = {
            'id': id_receive,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=1000)
        }
        token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')

        session['Authorization'] = token
        return jsonify({'result': 'success'}), 200
    else:
        return jsonify({'result': 'fail', 'errorField': 'userId', 'msg': '아이디(로그인 전용 아이디) 또는 비밀번호를 잘못 입력했습니다.<br/> 입력하신 내용을 다시 확인해주세요.'})


@app.route('/api/join', methods=['POST'])
def api_join():
    id_receive = request.form['id_give']
    pw_receive = request.form['pw_give']
    nickname_receive = request.form['nickname_give']

    if (db.user.find_one({'id': id_receive}) is not None):
        return jsonify({'result': 'fail', 'errorField': 'userId', 'msg': '이미 존재하는 아이디 입니다.'})
    elif (db.user.find_one({'nick': nickname_receive})):
        return jsonify({'result': 'fail', 'errorField': 'userNickname', 'msg': '이미 존재하는 닉네임 입니다.'}), 401

    pw_hash = hashlib.sha256(pw_receive.encode('utf-8')).hexdigest()

    db.user.insert_one(
        {'id': id_receive, 'pw': pw_hash, 'nick': nickname_receive})

    return jsonify({'result': 'success'}), 200


@app.route('/detail/<id>', methods=['GET', 'POST'])
def detail(id):
    if 'Authorization' in session:
        token_receive = session['Authorization']
        try:
            payload = jwt.decode(token_receive, SECRET_KEY,
                                 algorithms=['HS256'])
            db.user.find_one({"id": payload['id']})
            data = read_article(id)
            commentData = show_comment(id)
            if data['content'] == '':
                data['content'] = 'ChatGPT가 열심히 답변 중입니다. 잠시만 기다려주세요!'

            return render_template('detail.html', isLogin=True, title=data['title'], nickname=data['nickname'], content=data['content'], date=data['date'], commentData=commentData, isAnswer=data['withAnswer'], id=id)
        except jwt.ExpiredSignatureError:
            session.pop('Authorization', None)
            return redirect(url_for("redirectPage", alert="로그인 시간이 만료되었습니다. 다시 로그인 해주세요."))
        except jwt.exceptions.DecodeError:
            session.pop('Authorization', None)
            return redirect(url_for("redirectPage", alert="로그인 정보가 존재하지 않아 로그아웃 되었습니다."))
    else:
        data = read_article(id)
        commentData = show_comment(id)
        if data['content'] == '':
            data['content'] = 'ChatGPT가 열심히 답변 중입니다. 잠시만 기다려주세요!'
        return render_template('detail.html', title=data['title'], nickname=data['nickname'], content=data['content'], date=data['date'], commentData=commentData, isAnswer=data['withAnswer'], id=id)


@app.route('/logout')
def logout():
    session.pop('Authorization', None)
    return render_template('index.html')


def read_article(id):
    filter = {'_id': bson.ObjectId(id)}
    askData = db.askBoard.find_one(filter)

    detailData = {
        'title': askData['title'],
        'content': askData['content'],
        'nickname': askData['nickname'],
        'withAnswer': askData['withAnswer'],
        'date': datetime.datetime.fromtimestamp(askData['date']),
    }
    return detailData


@app.route('/api/ask/list', methods=['GET'])
def show_articles():
    filter = {}
    project = {}
    rs = list()
    docs = list(db.askBoard.find(filter, project).sort('date', -1))

    for askData in docs:
        item = {
            '_id': str(askData['_id']),
            'title': askData['title'],
            'content': askData['content'],
            'nickname': askData['nickname'],
            'date': datetime.datetime.fromtimestamp(askData['date'])
        }
        rs.append(item)

    return jsonify({'asks': rs}), 200


@app.route('/api/isGPTAnswer/<id>', methods=['GET'])
def isGPTAnswer(id):
    filter = {'_id': bson.ObjectId(id)}
    data = db.askBoard.find_one(filter)
    return jsonify({'isGPTAnswer': data['withAnswer'], 'content': data['content']}), 200


@app.route('/api/ask/create', methods=['POST'])
def post_article():
    title = request.form['title']
    nickname = getUserNickName()
    now = int(time.time())
    askData = {'title': title, 'content': "",
               'nickname': nickname, 'date': now, 'withAnswer': False}
    result = db.askBoard.insert_one(askData)
    askData['_id'] = str(result.inserted_id)

    # Start the chatgpt_comment function in a separate thread
    thread1 = threading.Thread(
        target=chatgpt_comment, args=(askData['_id'], title))
    thread1.start()

    # Return the response immediately with data:1
    return jsonify({'msg': '질문이 등록되었습니다.', 'data': askData}), 200


def chatgpt_comment(id, title):
    messages = [
        {"role": "system", "content": '개요에 맞게 1,000자 이내로 작성해줘.'}]
    messages.append({"role": "user", "content": title})
    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo", messages=messages)
    chatgpt_reply = completion.choices[0].message["content"].replace(
        "\n", "<br/>")
    db.askBoard.update_one({'_id': bson.ObjectId(id)}, {
        "$set": {"content": chatgpt_reply, 'withAnswer': True}})


@app.route('/api/comment/create/<id>', methods=['POST'])
def post_comment(id):
    myComment = request.form['myComment']
    now = int(time.time())
    nickname = getUserNickName()
    commentData = {'postid': id, 'comment': myComment,
                   'nickname': nickname, 'date': now}
    db.commentBoard.insert_one(commentData)
    # return jsonify({'msg': '답변이 등록되었습니다.'}), 200
    return redirect(url_for("detail", id=id))


def show_comment(id):
    filter = {'postid': id}
    project = {}
    rs = list()
    docs = list(db.commentBoard.find(filter, project).sort('date', 1))
    for memo in docs:
        item = {
            'nickname': memo['nickname'],
            'comment': memo['comment'],
            # '_id': str(memo['_id']),
            'date': datetime.datetime.fromtimestamp(memo['date'])
        }
        rs.append(item)

    return rs


def getUserNickName():
    if 'Authorization' in session:
        token_receive = session['Authorization']
        try:
            payload = jwt.decode(token_receive, SECRET_KEY,
                                 algorithms=['HS256'])
            user_info = db.user.find_one({"id": payload['id']})
            return user_info["nick"]
        except jwt.ExpiredSignatureError:
            session.pop('Authorization', None)
            return redirect(url_for("redirectPage", alert="로그인 시간이 만료되었습니다. 다시 로그인 해주세요."))
        except jwt.exceptions.DecodeError:
            session.pop('Authorization', None)
            return redirect(url_for("redirectPage", alert="로그인 정보가 존재하지 않아 로그아웃 되었습니다."))
    else:
        return redirect(url_for("redirectPage", alert="로그인 정보가 존재하지 않아 로그아웃 되었습니다."))


@app.route('/redirect')
def redirectPage():
    alert = request.args.get('alert')
    session.pop('Authorization', None)
    return render_template('redirect.html', alert=alert)


if __name__ == '__main__':
    app.run('0.0.0.0', port=5000, debug=True)
