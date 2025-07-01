import os
import json
import base64
from flask import Flask, render_template, request, session, redirect, url_for
from flask_socketio import SocketIO, emit, join_room
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Random import get_random_bytes
from Crypto.Hash import SHA256
from Crypto.Signature import pkcs1_15
from Crypto.Util.Padding import pad, unpad

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Thay đổi thành key bí mật thực tế
socketio = SocketIO(app)

# Cấu hình file
USERS_FILE = "users.json"
SESSIONS_DIR = "sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)


# Hàm helper đã sửa lỗi
def load_users():
    # Nếu file không tồn tại, trả về dict rỗng
    if not os.path.exists(USERS_FILE):
        return {}

    # Nếu file tồn tại nhưng trống, trả về dict rỗng
    if os.path.getsize(USERS_FILE) == 0:
        return {}

    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        # Trường hợp file bị hỏng, trả về dict rỗng
        return {}


def save_user(username, password_hash, public_key, private_key):
    users = load_users()
    users[username] = {
        "password_hash": password_hash,
        "public_key": public_key,
        "private_key": private_key
    }
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=4)


def save_session(sender, receiver, session_data):
    filename = f"{SESSIONS_DIR}/{sender}_{receiver}.json"
    with open(filename, "w") as f:
        json.dump(session_data, f)


def load_session(sender, receiver):
    # Thử tìm session theo thứ tự sender_receiver
    filename = f"{SESSIONS_DIR}/{sender}_{receiver}.json"
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    
    # Nếu không tìm thấy, thử tìm theo thứ tự receiver_sender
    filename = f"{SESSIONS_DIR}/{receiver}_{sender}.json"
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    
    return None


# Routes
@app.route("/")
def index():
    if "username" not in session:
        return redirect(url_for("login"))
    users = load_users()
    return render_template("index.html",
                           username=session["username"],
                           users=[u for u in users.keys() if u != session["username"]])


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        users = load_users()

        if username not in users:
            return render_template("login.html", error="User not found")

        # Verify password hash
        h = SHA256.new(password.encode())
        if h.hexdigest() != users[username]["password_hash"]:
            return render_template("login.html", error="Invalid password")

        session["username"] = username
        return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        confirm = request.form["confirm"]

        if password != confirm:
            return render_template("register.html", error="Passwords don't match")

        users = load_users()
        if username in users:
            return render_template("register.html", error="Username already exists")

        # Generate RSA key pair
        key = RSA.generate(2048)
        public_key = key.publickey().export_key().decode()
        private_key = key.export_key().decode()

        # Hash password
        h = SHA256.new(password.encode())

        # Save user
        save_user(username, h.hexdigest(), public_key, private_key)

        session["username"] = username
        return redirect(url_for("index"))

    return render_template("register.html")


@app.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("login"))


# SocketIO Handlers
@socketio.on("connect")
def handle_connect():
    if "username" not in session:
        return False


@socketio.on("init_chat")
def handle_init_chat(data):
    sender = session["username"]
    receiver = data["receiver"]

    users = load_users()
    if receiver not in users:
        socketio.emit("chat_error", {"message": "User not found"})
        return

    # Kiểm tra xem session đã tồn tại chưa
    existing_session = load_session(sender, receiver)
    if existing_session:
        # Nếu session đã tồn tại, gửi lại thông tin để thiết lập kết nối
        socketio.emit("aes_key_exchange", {
            "sender": receiver,
            "encrypted_aes_key": "reuse_existing",
            "signature": "reuse_existing"
        })
        return

    # Generate AES key
    aes_key = get_random_bytes(32)
    
    # Encrypt AES key with receiver's public key
    receiver_pub_key = RSA.import_key(users[receiver]["public_key"])
    cipher_rsa = PKCS1_v1_5.new(receiver_pub_key)
    encrypted_aes_key_for_receiver = cipher_rsa.encrypt(aes_key)
    
    # Encrypt AES key with sender's public key (để sender cũng có thể sử dụng)
    sender_pub_key = RSA.import_key(users[sender]["public_key"])
    cipher_rsa = PKCS1_v1_5.new(sender_pub_key)
    encrypted_aes_key_for_sender = cipher_rsa.encrypt(aes_key)

    # Sign metadata (sender + receiver)
    metadata = f"{sender}:{receiver}".encode()
    h_metadata = SHA256.new(metadata)
    sender_priv_key = RSA.import_key(users[sender]["private_key"])
    signature = pkcs1_15.new(sender_priv_key).sign(h_metadata)

    # Save session cho cả hai chiều
    session_data = {
        "aes_key": base64.b64encode(aes_key).decode(),
        "iv": None,
        "initiated_by": sender
    }
    save_session(sender, receiver, session_data)
    save_session(receiver, sender, session_data)

    # Send encrypted AES key and signature to sender
    socketio.emit("aes_key_exchange", {
        "sender": receiver,
        "encrypted_aes_key": base64.b64encode(encrypted_aes_key_for_sender).decode(),
        "signature": base64.b64encode(signature).decode()
    })

    # Also send to receiver if online
    socketio.emit("aes_key_exchange", {
        "sender": sender,
        "encrypted_aes_key": base64.b64encode(encrypted_aes_key_for_receiver).decode(),
        "signature": base64.b64encode(signature).decode()
    }, room=f"user_{receiver}")


@socketio.on("join")
def handle_join():
    if "username" in session:
        join_room(f"user_{session['username']}")


@socketio.on("send_message")
def handle_send_message(data):
    sender = session["username"]
    receiver = data["receiver"]
    message = data["message"]

    # Load session
    session_data = load_session(sender, receiver)
    if not session_data:
        socketio.emit("chat_error", {"message": "Session not established"})
        return

    aes_key = base64.b64decode(session_data["aes_key"])

    # Encrypt message
    iv = get_random_bytes(16)
    cipher = AES.new(aes_key, AES.MODE_CBC, iv)
    ciphertext = cipher.encrypt(pad(message.encode(), AES.block_size))

    # Calculate hash
    h = SHA256.new(iv + ciphertext)

    # Sign the hash
    users = load_users()
    priv_key = RSA.import_key(users[sender]["private_key"])
    signature = pkcs1_15.new(priv_key).sign(h)

    # Prepare message package
    msg_package = {
        "sender": sender,
        "iv": base64.b64encode(iv).decode(),
        "cipher": base64.b64encode(ciphertext).decode(),
        "hash": h.hexdigest(),
        "signature": base64.b64encode(signature).decode()
    }

    # Send to receiver
    socketio.emit("receive_message", msg_package, room=f"user_{receiver}")


@socketio.on("verify_message")
def handle_verify_message(data):
    sender = data["sender"]
    receiver = session["username"]

    # Load session
    session_data = load_session(sender, receiver)
    if not session_data:
        socketio.emit("chat_error", {"message": "Session not established"})
        return

    # Get receiver's private key to decrypt AES key
    users = load_users()
    priv_key = RSA.import_key(users[receiver]["private_key"])

    # Verify signature
    try:
        h_received = SHA256.new(
            base64.b64decode(data["iv"]) +
            base64.b64decode(data["cipher"])
        )
        sender_pub_key = RSA.import_key(users[sender]["public_key"])
        pkcs1_15.new(sender_pub_key).verify(
            h_received,
            base64.b64decode(data["signature"])
        )

        # Decrypt message
        aes_key = base64.b64decode(session_data["aes_key"])
        iv = base64.b64decode(data["iv"])
        ciphertext = base64.b64decode(data["cipher"])

        cipher = AES.new(aes_key, AES.MODE_CBC, iv)
        plaintext = unpad(cipher.decrypt(ciphertext), AES.block_size).decode()

        # Send ACK
        socketio.emit("message_verified", {
            "sender": sender,
            "message": plaintext,
            "status": "success"
        })

        # Also notify sender
        socketio.emit("message_status", {
            "receiver": receiver,
            "status": "delivered",
            "message": plaintext
        }, room=f"user_{sender}")

    except (ValueError, TypeError):
        # Send NACK
        socketio.emit("message_verified", {
            "sender": sender,
            "message": "Message verification failed",
            "status": "error"
        })

        # Notify sender
        socketio.emit("message_status", {
            "receiver": receiver,
            "status": "failed",
            "error": "Verification failed"
        }, room=f"user_{sender}")


@socketio.on("load_unread_messages")
def handle_load_unread_messages(data):
    if "username" not in session:
        return
    
    sender = data.get("sender")
    receiver = session["username"]
    
    # Trong ứng dụng thực tế, bạn sẽ tải tin nhắn chưa đọc từ cơ sở dữ liệu
    # Ở đây chúng ta chỉ gửi thông báo rằng không có tin nhắn chưa đọc
    socketio.emit("unread_messages", {
        "sender": sender,
        "messages": []
    })


if __name__ == "__main__":

    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w") as f:
            json.dump({}, f)

    socketio.run(app, debug=True)