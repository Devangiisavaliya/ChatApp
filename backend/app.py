import time

from flask import Flask, jsonify
from flask import render_template
from flask import request
from flask import redirect
from flask import session

from flask_socketio import SocketIO
from flask_socketio import emit
from flask_socketio import join_room

from pymsgbox import password
from werkzeug.utils import secure_filename
import random
import smtplib

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import mysql.connector
import bcrypt
import os

app = Flask(__name__)

app.secret_key = "secretkey"
EMAIL_ADDRESS = "devangisavaliya3@gmail.com"

EMAIL_PASSWORD = "ttss heho myhc xsdq"

socketio = SocketIO(app,
    cors_allowed_origins="*",
    async_mode="threading")

online_users = {}
group_online_users = {}

# =========================
# UPLOAD FOLDERS
# =========================
PROFILE_UPLOAD_FOLDER = "static/uploads"

CHAT_FILE_FOLDER = "static/chat_files"

IMAGE_UPLOAD_FOLDER = "static/chat_images"

os.makedirs(
    IMAGE_UPLOAD_FOLDER,
    exist_ok=True
)
VOICE_FOLDER = "static/voice_notes"

os.makedirs(
    VOICE_FOLDER,
    exist_ok=True
)

app.config["PROFILE_UPLOAD_FOLDER"] = PROFILE_UPLOAD_FOLDER

app.config["CHAT_FILE_FOLDER"] = CHAT_FILE_FOLDER

os.makedirs(PROFILE_UPLOAD_FOLDER, exist_ok=True)

os.makedirs(CHAT_FILE_FOLDER, exist_ok=True)


# =========================
# DATABASE CONNECTION
# =========================
def get_connection():

    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="chatapp"
    )

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = request.form["username"]

        password = request.form["password"]

        email = request.form["email"]

        photo = request.files.get("photo")

        filename = ""

        if photo and photo.filename != "":

            filename = secure_filename(photo.filename)

            photo.save(
                os.path.join(
                    PROFILE_UPLOAD_FOLDER,
                    filename
                )
            )

        otp = str(
            random.randint(
                100000,
                999999
            )
        )

        send_otp(
            email,
            otp
        )

        session["otp"] = otp

        session["register_data"] = {
            "username": username,
            "password": password,
            "email": email,
            "profile_photo": filename
        }

        return redirect("/verify_otp")

    return render_template("register.html")

# =========================
# LOGIN
# =========================
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form["username"]

        password = request.form["password"]

        connection = get_connection()

        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT *
            FROM users
            WHERE username=%s
            """,
            (username,)
        )

        user = cursor.fetchone()

        if user and bcrypt.checkpw(
            password.encode("utf-8"),
            user["password"].encode("utf-8")
        ):

            session["username"] = user["username"]

            session["profile_photo"] = user["profile_photo"]

            online_users[username] = True

            cursor.execute(
                """
                UPDATE users
                SET status='online'
                WHERE username=%s
                """,
                (username,)
            )

            connection.commit()

            cursor.close()
            connection.close()

            return redirect("/")

        cursor.close()
        connection.close()

        return "Invalid Username or Password"

    return render_template("login.html")


# =========================
# LOGOUT
# =========================
@app.route("/logout")
def logout():

    if "username" in session:

        username = session["username"]

        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute("""
            UPDATE users
            SET status='offline',
             last_seen=NOW()
            WHERE username=%s
        """, (username,))

        connection.commit()

        cursor.close()

        connection.close()

    session.clear()

    return redirect("/login")


# =========================
# USERS PAGE
# =========================
@app.route("/")
def home():

    if "username" not in session:
        return redirect("/login")

    connection = get_connection()

    cursor = connection.cursor(dictionary=True)

    # USERS
    cursor.execute("""
        SELECT username,status,profile_photo
        FROM users
        WHERE username != %s
    """, (session["username"],))

    users = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "users.html",
        users=users,
        receiver=None
    )



# =========================
# CREATE GROUP
# =========================
@app.route(
    "/create_group",
    methods=["GET", "POST"]
)
def create_group():

    if "username" not in session:
        return redirect("/login")

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    # GET ALL USERS
    cursor.execute("""
        SELECT username
        FROM users
        WHERE username != %s
    """, (session["username"],))

    users = cursor.fetchall()

    if request.method == "POST":

        group_name = request.form.get(
            "group_name"
        )

        selected_users = request.form.getlist(
            "members"
        )

        group_image = request.files.get(
         "group_image"
        )

        image_name = None

        if group_image and group_image.filename != "":

            image_name = group_image.filename

        image_path = os.path.join(
            "static/uploads",
            image_name
        )

        group_image.save(image_path)

       # INSERT GROUP
        sql = """
                INSERT INTO groups_table
                (
                    group_name,
                    created_by,
                    group_image,
                    admin
                )
                VALUES (%s, %s, %s, %s)
                """

        values = (
                    group_name,
                    session["username"],
                    image_name,
                    session["username"]
                )

        cursor.execute(sql, values)

        # INSERT MEMBERS
        for member in selected_users:

            cursor.execute("""
                INSERT INTO group_members
                (
                    group_name,
                    username,
                    role
                )
                VALUES (%s, %s, %s)
            """, (group_name, member, "member"))

        # ADD CREATOR ALSO
        cursor.execute("""
            INSERT INTO group_members
            (
                group_name,
                username,
                role
            )
            VALUES (%s, %s, %s)
        """, (
            group_name,
            session["username"],
            "admin"
        ))

        connection.commit()

        cursor.close()
        connection.close()

        return redirect("/groups")

    cursor.close()
    connection.close()

    return render_template(
        "create_group.html",
        users=users
    )

# =========================
# GROUP LIST
# =========================

@app.route("/groups")
@app.route("/groups/chat/<group_name>")
def groups(group_name=None):

    if "username" not in session:
        return redirect("/login")

    connection = get_connection()

    cursor = connection.cursor(dictionary=True)

    # ONLY USER GROUPS
    cursor.execute("""
        SELECT groups_table.*
        FROM groups_table
        INNER JOIN group_members
        ON groups_table.group_name = group_members.group_name
        WHERE group_members.username = %s
        ORDER BY groups_table.id DESC
    """, (session["username"],))

    groups = cursor.fetchall()

    selected_group = None

    messages = []

    selected_group_members = []

    # SELECTED GROUP
    if group_name:

        # GROUP DETAILS
        cursor.execute("""
            SELECT *
            FROM groups_table
            WHERE group_name=%s
        """, (group_name,))

        selected_group = cursor.fetchone()

        # GROUP MESSAGES
        cursor.execute("""
            SELECT *
            FROM group_messages
            WHERE group_name=%s
            ORDER BY id ASC
        """, (group_name,))

        messages = cursor.fetchall()

        # GROUP MEMBERS
        cursor.execute("""
            SELECT *
            FROM group_members
            WHERE group_name=%s
        """, (group_name,))

        selected_group_members = cursor.fetchall()

    cursor.close()

    connection.close()

    return render_template(
        "groups.html",
        groups=groups,
        selected_group=selected_group,
        selected_group_members=selected_group_members,
        messages=messages,
        group_name=group_name,
        username=session["username"]
    )
# =========================
# REMOVE MEMBER
# =========================

@app.route(
    "/remove_member/<group_name>/<username>"
)
def remove_member(
    group_name,
    username
):

    if "username" not in session:
        return redirect("/login")

    connection = get_connection()

    cursor = connection.cursor(dictionary=True)

    # CHECK ADMIN
    cursor.execute("""
        SELECT *
        FROM group_members
        WHERE group_name=%s
        AND username=%s
        AND role='admin'
    """, (
        group_name,
        session["username"]
    ))

    admin = cursor.fetchone()

    if not admin:

        return "Only admin can remove members"

    # REMOVE MEMBER
    cursor.execute("""
        DELETE FROM group_members
        WHERE group_name=%s
        AND username=%s
    """, (
        group_name,
        username
    ))

    connection.commit()

    cursor.close()

    connection.close()

    return redirect(f"/groups/chat/{group_name}")
# =========================
# ADD MEMBER
# =========================

@app.route(
    "/add_member/<group_name>",
    methods=["GET", "POST"]
)
def add_member(group_name):

    if "username" not in session:
        return redirect("/login")

    connection = get_connection()

    cursor = connection.cursor(dictionary=True)

    # CHECK ADMIN
    cursor.execute("""
        SELECT *
        FROM group_members
        WHERE group_name=%s
        AND username=%s
        AND role='admin'
    """, (
        group_name,
        session["username"]
    ))

    admin = cursor.fetchone()

    if not admin:

        return "Only admin can add members"

    # GET USERS NOT IN GROUP
    cursor.execute("""
        SELECT username
        FROM users
        WHERE username NOT IN
        (
            SELECT username
            FROM group_members
            WHERE group_name=%s
        )
    """, (group_name,))

    users = cursor.fetchall()

    # POST
    if request.method == "POST":

        members = request.form.getlist(
                "members"
            )

        for member in members:

            cursor.execute("""
                INSERT INTO group_members
                (
                    group_name,
                    username,
                    role
                )
                VALUES (%s,%s,%s)
            """, (
                group_name,
                member,
                "member"
            ))

        connection.commit()

        cursor.close()

        connection.close()

        return redirect(
            f"/groups/chat/{group_name}"
        )

    cursor.close()

    connection.close()

    return render_template(
        "add_member.html",
        users=users
    )
# =========================
# GROUP CHAT PAGE
# =========================
@app.route("/group_chat/<group_name>")
def group_chat(group_name):

    if "username" not in session:
        return redirect("/login")

    connection = get_connection()

    cursor = connection.cursor(dictionary=True)

    # GROUP MESSAGES
    sql = """
    SELECT *
    FROM group_messages
    WHERE group_name=%s

    AND (
        deleted_by IS NULL
        OR deleted_by=''
        OR deleted_by NOT LIKE %s
    )

    ORDER BY id ASC
    """

    cursor.execute(
    sql,
    (
        group_name,
        "%" + session["username"] + "%"
    )
    )

    messages = cursor.fetchall()

    # GROUP DETAILS
    cursor.execute("""
        SELECT *
        FROM groups_table
        WHERE group_name=%s
    """, (group_name,))

    group_data = cursor.fetchone()
    # =========================
    # GROUP MEMBERS
    # =========================

    cursor.execute("""
            SELECT *
            FROM group_members
            WHERE group_name=%s
        """, (group_name,))

    selected_group_members = cursor.fetchall()
    cursor.close()

    connection.close()
    
    return render_template(
    "group_chat.html",

    group_name=group_name,

    messages=messages,

    username=session["username"],

    group_data=group_data,

    selected_group_members=selected_group_members,

    selected_group=group_data
)

# =========================
# PRIVATE CHAT PAGE
# =========================
@app.route("/chat/<receiver>")
def private_chat(receiver):

    if "username" not in session:
        return redirect("/login")

    sender = session["username"]

    connection = get_connection()

    cursor = connection.cursor(dictionary=True)

    # CHAT MESSAGES
    sql = """
    SELECT *
    FROM private_messages
    WHERE
    (
        (
            sender=%s
            AND receiver=%s
        )
        OR
        (
            sender=%s
            AND receiver=%s
        )
    )
    AND
    (
        deleted_by IS NULL
        OR
        deleted_by != %s
    )
    ORDER BY id ASC
    """

    values = (
        sender,
        receiver,
        receiver,
        sender,
        sender
    )

    cursor.execute(sql, values)

    messages = cursor.fetchall()

    # USERS
    cursor.execute("""
        SELECT
            username,
            status,
            profile_photo,
            last_seen
        FROM users
        WHERE username != %s
    """, (sender,))

    users = cursor.fetchall()
    
     # RECEIVER INFO
    cursor.execute("""
        SELECT
            username,
            status,
            last_seen,
            profile_photo
        FROM users
        WHERE username=%s
    """, (receiver,))

    receiver_data = cursor.fetchone()

    cursor.close()

    connection.close()

    return render_template(
        "users.html",
        messages=messages,
        receiver=receiver,
        users=users,
        receiver_data=receiver_data,
        username=sender
    )

# =========================
# SEND GROUP MESSAGE
# =========================
@socketio.on("send_group_message")
def send_group_message(data):

    group_name = data["group_name"]

    sender = data["sender"]

    message = data["message"]

    file_name = data.get("file_name", "")

    voice = data["voice"]
    
    reply_message = data.get("reply_message", "")

    connection = get_connection()

    cursor = connection.cursor()

    sql = """
    INSERT INTO group_messages
    (
        group_name,
        sender,
        message,
        file_name,
        voice,
        reply_message,
        delivered_status,
        seen_status
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """

    values = (
        group_name,
        sender,
        message,
        file_name,
        voice,
        reply_message,
        "Delivered",
        "Delivered"
    )

    cursor.execute(sql, values)

    connection.commit()

    message_id = cursor.lastrowid

    cursor.close()

    connection.close()

    socketio.emit(
        "receive_group_message",
        {
            "message_id": message_id,
            "sender": sender,
            "message": message,
            "file_name": file_name,
            "voice": voice,
            "reply_message": reply_message,
        },
        room=group_name
    )
# =========================
# SOCKET JOIN
# =========================
@socketio.on("join")
def on_join(data):

    room = data["room"]

    join_room(room)

    # USER ONLINE
    if "username" in session:
        if "username" in session:
            online_users[session["username"]] = True
        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE users
            SET status='online'
            WHERE username=%s
            """,
            (session["username"],)
        )

        connection.commit()

        cursor.close()

        connection.close()

        # REALTIME ONLINE UPDATE
        socketio.emit(
            "user_status",
            {
                "username":
                    session["username"],

                "status":
                    "online"
            }
        )
        
# =========================
# DISCONNECT
# =========================
@socketio.on("disconnect")
def disconnect_user():

    if "username" in session:

        username = session["username"]

        if username in online_users:
            del online_users[username]

        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE users
            SET status='offline'
            WHERE username=%s
            """,
            (username,)
        )

        connection.commit()

        cursor.close()

        connection.close()

        socketio.emit(
            "user_status",
            {
                "username": username,
                "status": "offline"
            }
        )
# =========================
# SEND PRIVATE MESSAGE
# =========================
@socketio.on("send_message")
def handle_send_message(data):

    sender = data["sender"]

    receiver = data["receiver"]

    message = data.get("message", "")

    file_name = data.get("file_name")

    voice = data.get("voice", "")
    
    reply_message = data.get("reply_message", "")

    room = data["room"]

    connection = get_connection()

    cursor = connection.cursor()

    sql = """
    INSERT INTO private_messages
    (
        sender,
        receiver,
        message,
        file_name,
        voice,
        reply_message,
        message_type,
        seen_status
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """

    values = (
        sender,
        receiver,
        message,
        file_name,
        voice,
        data.get("reply_message", ""),
        "text",
        "Delivered"
    )

    cursor.execute(sql, values)

    connection.commit()

    message_id = cursor.lastrowid

    cursor.close()

    connection.close()

    socketio.emit(
        "receive_message",
        {
            "message_id": message_id,
            "sender": sender,
            "message": message,
            "file_name": file_name,
            "voice": voice,
            "reply_message": reply_message,
            "status": "Delivered"
        },
        room=room
    )

# =========================
# TYPING STATUS
# =========================
@socketio.on("typing")
def typing(data):

    emit(
        "show_typing",
        {
            "username": data["username"]
        },
        room=data["room"],
        include_self=False
    )

# =========================
# MESSAGE SEEN
# =========================
@socketio.on("message_seen")
def message_seen(data):

    message_id = data["message_id"]

    room = data["room"]

    connection = get_connection()

    cursor = connection.cursor()

    # UPDATE DATABASE
    sql = """
    UPDATE private_messages
    SET seen_status='Seen'
    WHERE id=%s
    """

    cursor.execute(
        sql,
        (message_id,)
    )

    connection.commit()

    cursor.close()

    connection.close()

    # SEND REALTIME UPDATE
    socketio.emit(
        "seen_update",
        {
            "message_id": message_id,
            "status": "Seen"
        },
        room=room
    )
# =========================
# SEND REACTION
# =========================

@socketio.on("send_reaction")
def send_reaction(data):

    message_id = data["message_id"]

    emoji = data["emoji"]

    room = data["room"]

    connection = get_connection()

    cursor = connection.cursor()

    # SAVE REACTION

    cursor.execute(
        """
        UPDATE private_messages
        SET reaction=%s
        WHERE id=%s
        """,
        (
            emoji,
            message_id
        )
    )

    connection.commit()

    cursor.close()

    connection.close()

    # REALTIME UPDATE

    socketio.emit(
        "receive_reaction",
        {
            "message_id": message_id,
            "emoji": emoji
        },
        room=room
    )
    socketio.emit(
    "reaction_notification",
    {
        "message":
        f"{session['username']} reacted {emoji}"
    },
    room=room
)
# =========================
# GROUP JOIN
# =========================

@socketio.on("join_group")
def join_group(data):

    group_name = data["group_name"]

    join_room(group_name)

    if "username" in session:

        username = session["username"]

        # SAVE ONLINE USER
        online_users[username] = True

        emit(
            "group_joined",
            {
                "message": username + " joined group"
            },
            room=group_name
        )

        # SEND ONLINE COUNT
        emit_group_online_count(group_name)



# =========================
# GET GROUP ONLINE MEMBERS
# =========================

@socketio.on("get_group_online_members")
def get_group_online_members(data):

    group_name = data["group_name"]

    emit_group_online_count(group_name)



# =========================
# EMIT GROUP ONLINE COUNT
# =========================

def emit_group_online_count(group_name):

    connection = get_connection()

    cursor = connection.cursor(dictionary=True)

    # GET ALL GROUP MEMBERS
    cursor.execute("""
        SELECT username
        FROM group_members
        WHERE group_name=%s
    """, (group_name,))

    members = cursor.fetchall()

    online_count = 0

    for member in members:

        if member["username"] in online_users:

            online_count += 1

    emit(
        "group_online_members",
        {
            "count": online_count
        },
        room=group_name
    )

    cursor.close()

    connection.close()
# =========================
# GROUP MESSAGE SEEN
# =========================
@socketio.on("group_message_seen")
def group_message_seen(data):

    message_id = data["message_id"]

    group_name = data["group_name"]

    connection = get_connection()

    cursor = connection.cursor()

    sql = """
    UPDATE group_messages
    SET seen_status='Seen'
    WHERE id=%s
    """

    cursor.execute(
        sql,
        (message_id,)
    )

    connection.commit()

    cursor.close()

    connection.close()

    # SEND REALTIME UPDATE
    socketio.emit(
        "group_seen_update",
        {
            "message_id":
                message_id,

            "status":
                "Seen"
        },
        room=group_name
    )
    
# =========================
# GROUP TYPING
# =========================
@socketio.on("group_typing")
def group_typing(data):

    socketio.emit(
        "show_group_typing",
        {
            "username":
                data["username"]
        },
        room=data["group_name"]
    )
    
    
# =========================
# UPLOAD IMAGE
# =========================
@app.route(
    "/upload_image",
    methods=["POST"]
)
def upload_image():

    image = request.files.get("image")

    if not image:
        return {
            "error": "No image"
        }

    filename = secure_filename(
            image.filename
        )

    image.save(
        os.path.join(
            IMAGE_UPLOAD_FOLDER,
            filename
        )
    )

    return {
        "filename": filename
    }

# =========================
# FILE UPLOAD
# =========================
@app.route("/upload_file", methods=["POST"])
def upload_file():

    file = request.files["file"]

    filename = file.filename

    upload_path = os.path.join(
        "static/uploads",
        filename
    )

    file.save(upload_path)

    return {
        "filename": filename
    }  
# =========================
# UPLOAD VOICE
# =========================
@app.route(
    "/upload_voice",
    methods=["POST"]
)
def upload_voice():

    audio = request.files.get("audio")

    if not audio:
        return {
            "error": "No audio"
        }

    filename = secure_filename(
            audio.filename
        )

    audio.save(
        os.path.join(
            VOICE_FOLDER,
            filename
        )
    )

    return {
        "filename": filename
    }
# =========================
# CALL USER
# =========================
@socketio.on("call_user")
def call_user(data):

    room = data["room"]

    emit(
        "incoming_call",
        {
            "offer": data["offer"],
            "type": data["type"]
        },
        room=room,
        include_self=False
    )
# =========================
# ANSWER CALL
# =========================
@socketio.on("answer_call")
def answer_call(data):

    emit(
        "call_answered",
        {
            "answer": data["answer"]
        },
        room=data["room"],
        include_self=False
    )


# =========================
# ICE CANDIDATE
# =========================
@socketio.on("ice_candidate")
def ice_candidate(data):

    emit(
        "ice_candidate",
        {
            "candidate": data["candidate"]
        },
        room=data["room"],
        include_self=False
    )

# =========================
# END CALL
# =========================
@socketio.on("end_call")
def end_call(data):

    emit(
        "call_ended",
        {},
        room=data["room"],
        include_self=False
    )
    
# =========================
# SETTINGS PAGE
# =========================

@app.route("/settings", methods=["GET", "POST"])
def settings():

    if 'username' not in session:

        return redirect("/login")

    if request.method == "POST":

        username = request.form["username"]

        profile_photo = request.files["profile_photo"]

        connection = get_connection()

        cursor = connection.cursor()

        filename = session.get('profile_photo')

        # PHOTO UPLOAD


        if profile_photo and profile_photo.filename != "":

         filename = str(int(time.time())) + "_" + secure_filename(profile_photo.filename)

        profile_photo.save(
            os.path.join(
                "static/uploads",
                filename
            )
        )

        # UPDATE DATABASE

        cursor.execute("""
            UPDATE users
            SET username=%s,
                profile_photo=%s
            WHERE username=%s
        """, (
            username,
            filename,
            session['username']
        ))

        connection.commit()

        # UPDATE SESSION

        session['username'] = username

        session['profile_photo'] = filename

        return redirect("/settings")

    return render_template("settings.html")
# =========================
# CHECK USER STATUS
# =========================
@socketio.on("check_user_status")
def check_user_status(data):

    username = data["username"]

    online = False

    if username in online_users:
        online = True

    emit(
        "user_status",
        {
            "online": online
        }
    )
# =========================
# GROUP REACTION
# =========================

@socketio.on("send_group_reaction")
def send_group_reaction(data):

    message_id = data["message_id"]

    emoji = data["emoji"]

    group_name = data["group_name"]

    connection = get_connection()

    cursor = connection.cursor()

    # SAVE REACTION

    cursor.execute(
        """
        UPDATE group_messages
        SET reaction=%s
        WHERE id=%s
        """,
        (
            emoji,
            message_id
        )
    )

    connection.commit()

    cursor.close()

    connection.close()

    # REALTIME UPDATE

    socketio.emit(
        "receive_group_reaction",
        {
            "message_id": message_id,
            "emoji": emoji
        },
        room=group_name
    )

    # NOTIFICATION

    socketio.emit(
        "reaction_notification",
        {
            "message":
            f"{session['username']} reacted {emoji}"
        },
        room=group_name
    )
# =========================
# DELETE FOR ME
# =========================

@app.route(
    "/delete_for_me/<int:message_id>",
    methods=["POST"]
)
def delete_for_me(message_id):

    if "username" not in session:
        return jsonify(
            {"success": False}
        )

    username = session["username"]

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        UPDATE private_messages
        SET deleted_by=%s
        WHERE id=%s
        """,
        (
            username,
            message_id
        )
    )

    connection.commit()

    cursor.close()

    connection.close()

    return jsonify(
        {"success": True}
    )
# =========================
# DELETE FOR EVERYONE
# =========================

@app.route(
    "/delete_for_everyone/<int:message_id>",
    methods=["POST"]
)
def delete_for_everyone(message_id):

    print("DELETE FOR EVERYONE =", message_id)

    if "username" not in session:
        print("NO SESSION")
        return jsonify({"success": False})

    username = session["username"]

    print("CURRENT USER =", username)

    connection = get_connection()

    cursor = connection.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT sender
        FROM private_messages
        WHERE id=%s
        """,
        (message_id,)
    )

    message = cursor.fetchone()

    print("MESSAGE =", message)

    if not message:
        print("MESSAGE NOT FOUND")
        return jsonify({"success": False})

    if message["sender"] != username:
        print("NOT OWNER")
        return jsonify({"success": False})

    print("UPDATING...")

    cursor.execute(
        """
        UPDATE private_messages
        SET deleted_for_everyone=1
        WHERE id=%s
        """,
        (message_id,)
    )

    connection.commit()

    print("UPDATED SUCCESS")

    cursor.close()
    connection.close()

    return jsonify({"success": True})

@app.route(
    "/group_delete_for_me/<int:message_id>",
    methods=["POST"]
)
def group_delete_for_me(message_id):
    username = session.get("username")

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT deleted_by
        FROM group_messages
        WHERE id=%s
        """,
        (message_id,)
    )

    row = cursor.fetchone()

    deleted_by = ""

    if row and row["deleted_by"]:
        deleted_by = row["deleted_by"]

    if username not in deleted_by:

        if deleted_by:
            deleted_by += "," + username
        else:
            deleted_by = username

        cursor.execute(
            """
            UPDATE group_messages
            SET deleted_by=%s
            WHERE id=%s
            """,
            (
                deleted_by,
                message_id
            )
        )

        conn.commit()

    cursor.close()
    conn.close()

    return jsonify(
        {
            "success": True
        }
    )
    
@app.route("/group_delete_for_everyone/<int:message_id>", methods=["POST"])
def group_delete_for_everyone(message_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE group_messages
        SET deleted_for_everyone=1
        WHERE id=%s
    """, (message_id,))

    conn.commit()

    cursor.close()
    conn.close()

    socketio.emit(
        "group_message_deleted",
        {
            "message_id": message_id
        }
    )

    return jsonify({"success": True})
def send_otp(email, otp):

    msg = MIMEMultipart()

    msg["From"] = EMAIL_ADDRESS

    msg["To"] = email

    msg["Subject"] = "OTP Verification"

    msg.attach(
        MIMEText(
            f"Your OTP is: {otp}",
            "plain"
        )
    )

    server = smtplib.SMTP(
        "smtp.gmail.com",
        587
    )

    server.starttls()

    server.login(
        EMAIL_ADDRESS,
        EMAIL_PASSWORD
    )

    server.send_message(msg)

    server.quit()

@app.route("/verify_otp", methods=["GET", "POST"])
def verify_otp():

    if request.method == "POST":

        user_otp = request.form["otp"]

        if user_otp == session.get("otp"):

            data = session["register_data"]

            hashed_password = bcrypt.hashpw(
                data["password"].encode("utf-8"),
                bcrypt.gensalt()
            ).decode("utf-8")

            connection = get_connection()

            cursor = connection.cursor()

            sql = """
            INSERT INTO users
            (
                username,
                password,
                email,
                profile_photo,
                status,
                is_verified
            )
            VALUES (%s,%s,%s,%s,%s,%s)
            """

            values = (
                data["username"],
                hashed_password,
                data["email"],
                data["profile_photo"],
                "offline",
                1
            )

            cursor.execute(
                sql,
                values
            )

            connection.commit()

            cursor.close()

            connection.close()

            session.pop("otp", None)

            session.pop("register_data", None)

            return redirect("/login")

        return "Invalid OTP"

    return render_template("verify_otp.html")

@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":

        email = request.form["email"]

        connection = get_connection()

        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT *
            FROM users
            WHERE email=%s
            """,
            (email,)
        )

        user = cursor.fetchone()

        cursor.close()
        connection.close()

        if not user:
            return "Email not found"

        otp = str(random.randint(100000, 999999))

        send_otp(email, otp)

        session["reset_otp"] = otp
        session["reset_email"] = email
        session["reset_username"] = user["username"]

        return redirect("/verify_reset_otp")

    return render_template("forgot_password.html")

@app.route("/verify_reset_otp", methods=["GET", "POST"])
def verify_reset_otp():

    if request.method == "POST":

        user_otp = request.form["otp"]

        if user_otp == session.get("reset_otp"):

            return redirect("/new_password")

        return "Invalid OTP"

    return render_template("verify_reset_otp.html")
    
import bcrypt

@app.route("/new_password", methods=["GET", "POST"])
def new_password():

    if request.method == "POST":

        password = request.form["password"]

        hashed_password = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        username = session.get("reset_username")

        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE users
            SET password=%s
            WHERE username=%s
            """,
            (
                hashed_password,
                username
            )
        )

        connection.commit()

        cursor.close()
        connection.close()

        session.pop("reset_otp", None)
        session.pop("reset_email", None)
        session.pop("reset_username", None)

        return redirect("/login")

    return render_template("new_password.html")
# =========================
# MAIN
# =========================
if __name__ == "__main__":

    socketio.run(
        app,
        debug=True
    )