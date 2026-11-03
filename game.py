import random
import string
import threading
import time

QUESTIONS = [
    {"question": "Which planet is known as the Red Planet?", "options": ["Venus", "Mars", "Jupiter", "Mercury"], "answer": 1, "category": "Science"},
    {"question": "What is the capital of Australia?", "options": ["Sydney", "Melbourne", "Canberra", "Perth"], "answer": 2, "category": "Geography"},
    {"question": "Which language is primarily used with Flask?", "options": ["Java", "Python", "C#", "Ruby"], "answer": 1, "category": "Technology"},
    {"question": "How many sides does a hexagon have?", "options": ["5", "6", "7", "8"], "answer": 1, "category": "General"},
    {"question": "Which ocean is the largest?", "options": ["Atlantic", "Indian", "Arctic", "Pacific"], "answer": 3, "category": "Geography"},
    {"question": "What does CPU stand for?", "options": ["Central Processing Unit", "Computer Personal Unit", "Core Program Utility", "Central Power User"], "answer": 0, "category": "Technology"},
    {"question": "Which gas do plants absorb from the atmosphere?", "options": ["Oxygen", "Nitrogen", "Carbon dioxide", "Hydrogen"], "answer": 2, "category": "Science"},
    {"question": "Who wrote 'Romeo and Juliet'?", "options": ["Charles Dickens", "William Shakespeare", "Jane Austen", "Mark Twain"], "answer": 1, "category": "Literature"},
    {"question": "What is 12 × 8?", "options": ["86", "92", "96", "108"], "answer": 2, "category": "Math"},
    {"question": "Which is the national animal of India?", "options": ["Lion", "Elephant", "Peacock", "Bengal tiger"], "answer": 3, "category": "India"},
]

class GameManager:
    def __init__(self, socketio):
        self.socketio = socketio
        self.rooms = {}
        self.sid_rooms = {}
        self.lock = threading.RLock()

    def _code(self):
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
            if code not in self.rooms:
                return code

    def _public_state(self, room):
        players = sorted(room["players"].values(), key=lambda p: (-p["score"], p["joined"]))
        return {
            "room_code": room["code"],
            "host_sid": room["host_sid"],
            "players": [{"name": p["name"], "score": p["score"], "connected": p["connected"], "answered": p["answered"]} for p in players],
            "status": room["status"],
            "question_index": room["question_index"],
            "total_questions": len(room["questions"]),
            "current_question": self._question_for(room) if room["status"] == "playing" else None,
            "seconds_left": max(0, int(room["deadline"] - time.time() + 0.999)) if room["status"] == "playing" else 0,
            "answered_count": sum(1 for p in room["players"].values() if p["answered"]),
            "player_count": len(room["players"]),
        }

    def _question_for(self, room):
        q = room["questions"][room["question_index"]]
        return {"question": q["question"], "options": q["options"], "category": q["category"]}

    def _emit_state(self, room):
        self.socketio.emit("game_state", self._public_state(room), to=room["code"])

    def _cancel_timer(self, room):
        timer = room.get("timer")
        if timer:
            timer.cancel()
            room["timer"] = None

    def create_room(self, sid, name):
        with self.lock:
            old = self.sid_rooms.get(sid)
            if old:
                self._remove_sid(sid, old)
            code = self._code()
            room = {"code": code, "host_sid": sid, "players": {}, "status": "lobby",
                    "question_index": 0, "questions": [], "deadline": 0, "timer": None,
                    "answers": {}, "joined_counter": 0}
            self.rooms[code] = room
            self._add_player(room, sid, name)
            return {"ok": True, "room_code": code, "state": self._public_state(room), "is_host": True}

    def _add_player(self, room, sid, name):
        room["joined_counter"] += 1
        room["players"][sid] = {"name": name, "score": 0, "answered": False,
                                "connected": True, "joined": room["joined_counter"]}
        self.sid_rooms[sid] = room["code"]

    def join_room(self, sid, name, code):
        with self.lock:
            room = self.rooms.get(code)
            if not room:
                return {"ok": False, "error": "Room not found. Check the code and try again."}
            if room["status"] != "lobby":
                return {"ok": False, "error": "This game has already started."}
            if len(room["players"]) >= 8:
                return {"ok": False, "error": "This room is full (maximum 8 players)."}
            if sid in self.sid_rooms:
                self._remove_sid(sid, self.sid_rooms[sid])
            self._add_player(room, sid, name)
            return {"ok": True, "room_code": code, "state": self._public_state(room), "is_host": False}

    def start_game(self, sid):
        with self.lock:
            code = self.sid_rooms.get(sid)
            room = self.rooms.get(code)
            if not room or room["host_sid"] != sid:
                return {"ok": False, "error": "Only the host can start the game."}
            if room["status"] != "lobby":
                return {"ok": False, "error": "The game has already started."}
            if len(room["players"]) < 2:
                return {"ok": False, "error": "At least 2 players are required."}
            room["questions"] = random.sample(QUESTIONS, len(QUESTIONS))
            room["question_index"] = 0
            room["status"] = "playing"
            self._begin_question(room)
            return {"ok": True}

    def _begin_question(self, room):
        self._cancel_timer(room)
        for player in room["players"].values():
            player["answered"] = False
        room["answers"] = {}
        room["deadline"] = time.time() + 15
        self._emit_state(room)
        code = room["code"]
        room["timer"] = threading.Timer(15, self._time_up, args=(code, room["question_index"]))
        room["timer"].daemon = True
        room["timer"].start()

    def submit_answer(self, sid, answer):
        with self.lock:
            code = self.sid_rooms.get(sid)
            room = self.rooms.get(code)
            if not room or room["status"] != "playing":
                return {"ok": False, "error": "There is no active question."}
            player = room["players"].get(sid)
            if not player or player["answered"]:
                return {"ok": False, "error": "Your answer has already been submitted."}
            if not isinstance(answer, int) or answer not in range(4):
                return {"ok": False, "error": "Invalid answer."}
            q = room["questions"][room["question_index"]]
            correct = answer == q["answer"]
            remaining = max(0, room["deadline"] - time.time())
            points = 100 + int(remaining * 3.33) if correct else 0
            player["score"] += points
            player["answered"] = True
            room["answers"][sid] = {"correct": correct, "points": points}
            self.socketio.emit("answer_feedback", {"correct": correct, "points": points,
                "correct_index": q["answer"] if len(room["answers"]) == len(room["players"]) else None}, to=sid)
            self._emit_state(room)
            if all(p["answered"] for p in room["players"].values()):
                self._reveal_question(room)
            return {"ok": True}

    def _time_up(self, code, question_index):
        with self.lock:
            room = self.rooms.get(code)
            if not room or room["status"] != "playing" or room["question_index"] != question_index:
                return
            for sid, player in room["players"].items():
                if not player["answered"]:
                    player["answered"] = True
                    room["answers"][sid] = {"correct": False, "points": 0}
                    self.socketio.emit("answer_feedback", {"correct": False, "points": 0, "timed_out": True}, to=sid)
            self._reveal_question(room)

    def _reveal_question(self, room):
        self._cancel_timer(room)
        q = room["questions"][room["question_index"]]
        self.socketio.emit("question_result", {
            "correct_index": q["answer"],
            "correct_answer": q["options"][q["answer"]],
            "answers": [{"name": room["players"][sid]["name"], **result} for sid, result in room["answers"].items() if sid in room["players"]]
        }, to=room["code"])
        room["status"] = "between"
        self._emit_state(room)

    def next_question(self, sid):
        with self.lock:
            code = self.sid_rooms.get(sid)
            room = self.rooms.get(code)
            if not room or room["host_sid"] != sid:
                return {"ok": False, "error": "Only the host can continue."}
            if room["status"] != "between":
                return {"ok": False, "error": "Wait for the current question to finish."}
            room["question_index"] += 1
            if room["question_index"] >= len(room["questions"]):
                room["status"] = "finished"
                self._emit_state(room)
                self.socketio.emit("game_finished", {"players": self._public_state(room)["players"]}, to=code)
            else:
                room["status"] = "playing"
                self._begin_question(room)
            return {"ok": True}

    def play_again(self, sid):
        with self.lock:
            code = self.sid_rooms.get(sid)
            room = self.rooms.get(code)
            if not room or room["host_sid"] != sid or room["status"] != "finished":
                return {"ok": False, "error": "Only the host can start a rematch."}
            for p in room["players"].values():
                p["score"] = 0
                p["answered"] = False
            room["questions"] = []
            room["question_index"] = 0
            room["status"] = "lobby"
            self._emit_state(room)
            return {"ok": True}

    def _remove_sid(self, sid, code):
        room = self.rooms.get(code)
        if room and sid in room["players"]:
            del room["players"][sid]
            if room["host_sid"] == sid and room["players"]:
                room["host_sid"] = next(iter(room["players"]))
            if not room["players"]:
                self._cancel_timer(room)
                self.rooms.pop(code, None)
        self.sid_rooms.pop(sid, None)

    def disconnect(self, sid):
        with self.lock:
            code = self.sid_rooms.get(sid)
            if not code:
                return None
            room = self.rooms.get(code)
            if not room:
                self.sid_rooms.pop(sid, None)
                return None
            player = room["players"].get(sid)
            if player:
                player["connected"] = False
                # Disconnected players remain in the room and retain their score.
            return {"room_code": code, "state": self._public_state(room)}
