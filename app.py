import os
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from game import GameManager

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-in-production")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
games = GameManager(socketio)

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/health")
def health():
    return {"status": "ok"}

@socketio.on("create_room")
def on_create_room(data):
    name = (data or {}).get("name", "").strip()
    if not name:
        emit("error_message", {"message": "Enter your player name."})
        return
    result = games.create_room(request.sid, name[:18])
    if result.get("ok"):
        join_room(result["room_code"])
        emit("room_created", result)
    else:
        emit("error_message", {"message": result["error"]})

@socketio.on("join_room")
def on_join_room(data):
    data = data or {}
    name = str(data.get("name", "")).strip()[:18]
    code = str(data.get("room_code", "")).strip().upper()
    if not name or not code:
        emit("error_message", {"message": "Enter your name and room code."})
        return
    result = games.join_room(request.sid, name, code)
    if result.get("ok"):
        join_room(code)
        emit("joined_room", result)
        socketio.emit("lobby_update", result["state"], to=code)
    else:
        emit("error_message", {"message": result["error"]})

@socketio.on("start_game")
def on_start_game(data):
    result = games.start_game(request.sid)
    if not result.get("ok"):
        emit("error_message", {"message": result["error"]})

@socketio.on("submit_answer")
def on_submit_answer(data):
    data = data or {}
    result = games.submit_answer(request.sid, data.get("answer"))
    if not result.get("ok"):
        emit("error_message", {"message": result["error"]})

@socketio.on("next_question")
def on_next_question():
    result = games.next_question(request.sid)
    if not result.get("ok"):
        emit("error_message", {"message": result["error"]})

@socketio.on("play_again")
def on_play_again():
    result = games.play_again(request.sid)
    if not result.get("ok"):
        emit("error_message", {"message": result["error"]})

@socketio.on("disconnect")
def on_disconnect():
    result = games.disconnect(request.sid)
    if result and result.get("room_code"):
        socketio.emit("lobby_update", result["state"], to=result["room_code"])


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), allow_unsafe_werkzeug=True)
