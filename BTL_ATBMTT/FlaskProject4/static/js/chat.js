document.addEventListener("DOMContentLoaded", function() {
    const socket = io();
    let currentUser = null;
    let aesKey = null;
    let sessionEstablished = false;

    // Join user room
    socket.emit("join");

    // Select user to chat with
    document.querySelectorAll(".user-item").forEach(item => {
        item.addEventListener("click", function(e) {
            e.preventDefault();
            const selectedUser = this.getAttribute("data-user");

            // Update UI
            document.querySelector("#current-chat-user").textContent = selectedUser;
            document.querySelector("#message-input").disabled = true; // Disable until session is established
            document.querySelector("#send-button").disabled = true;

            // Clear chat messages
            document.querySelector("#chat-messages").innerHTML = "";
            
            // Add system message
            addMessage("System", "Establishing secure connection...", "system-message");

            // Remove new message indicator
            this.classList.remove("has-new-message");
            const indicator = this.querySelector(".new-message-indicator");
            if (indicator) {
                indicator.remove();
            }

            // Initialize chat session
            currentUser = selectedUser;
            sessionEstablished = false;
            socket.emit("init_chat", { receiver: selectedUser });
        });
    });

    // Handle AES key exchange
    socket.on("aes_key_exchange", async (data) => {
        try {
            // Kiểm tra xem có phải là yêu cầu tái sử dụng session không
            if (data.encrypted_aes_key === "reuse_existing") {
                console.log("Reusing existing session with:", data.sender);
                sessionEstablished = true;
                
                // Enable message input
                document.querySelector("#message-input").disabled = false;
                document.querySelector("#send-button").disabled = false;
                document.querySelector("#message-input").focus();
                
                // Notify user
                addMessage("System", "Secure connection established with " + data.sender, "system-message");
                return;
            }
            
            // Here you would use the private key to decrypt the AES key
            // This is a simplified version - in a real app, you'd use WebCrypto or similar
            console.log("Received encrypted AES key:", data.encrypted_aes_key);
            console.log("Signature:", data.signature);

            // For demo purposes, we'll just store the encrypted key
            aesKey = data.encrypted_aes_key;
            sessionEstablished = true;

            // Enable message input
            document.querySelector("#message-input").disabled = false;
            document.querySelector("#send-button").disabled = false;
            document.querySelector("#message-input").focus();

            // Notify user
            addMessage("System", "Secure connection established with " + data.sender, "system-message");
        } catch (error) {
            console.error("Error establishing secure connection:", error);
            addMessage("System", "Error establishing secure connection", "error-message");
        }
    });

    // Send message function
    function sendMessage() {
        const messageInput = document.querySelector("#message-input");
        const message = messageInput.value.trim();
        
        if (!message || !currentUser) return;
        
        if (!sessionEstablished) {
            addMessage("System", "Secure connection not established yet. Please wait.", "error-message");
            return;
        }

        // Send the message
        socket.emit("send_message", {
            receiver: currentUser,
            message: message
        });

        // Add to chat
        addMessage("You", message, "sent-message");
        messageInput.value = "";
        messageInput.focus();
    }

    // Send message on button click
    document.querySelector("#send-button").addEventListener("click", sendMessage);
    
    // Send message on Enter key
    document.querySelector("#message-input").addEventListener("keypress", function(e) {
        if (e.key === "Enter") {
            e.preventDefault();
            sendMessage();
        }
    });

    // Receive message
    socket.on("receive_message", (data) => {
        // Kiểm tra xem tin nhắn có phải từ người đang chat không
        if (data.sender === currentUser) {
            // In a real app, you would decrypt and verify the message here
            // For now, we'll just show a placeholder until verification
            addMessage(data.sender, "Verifying message...", "received-message pending");

            // Verify the message
            socket.emit("verify_message", data);
        } else {
            // Nếu tin nhắn từ người khác, hiển thị thông báo
            const senderElement = document.createElement("div");
            senderElement.className = "new-message-notification";
            senderElement.innerHTML = `<strong>New message from ${data.sender}</strong>`;
            
            // Tìm user item tương ứng và thêm thông báo
            document.querySelectorAll(".user-item").forEach(item => {
                if (item.getAttribute("data-user") === data.sender) {
                    item.classList.add("has-new-message");
                    if (!item.querySelector(".new-message-indicator")) {
                        const indicator = document.createElement("span");
                        indicator.className = "new-message-indicator";
                        indicator.textContent = "🔴";
                        item.appendChild(indicator);
                    }
                }
            });
        }
    });

    // Message verification result
    socket.on("message_verified", (data) => {
        if (data.sender !== currentUser) return;

        if (data.status === "success") {
            // Update the message to show the verified content
            const messages = document.querySelectorAll(".received-message.pending");
            const lastMessage = messages[messages.length - 1];
            if (lastMessage) {
                lastMessage.innerHTML = `<strong>${data.sender}:</strong> ${data.message}`;
                lastMessage.classList.remove("pending");
            }
        } else {
            // Remove the pending message
            const messages = document.querySelectorAll(".received-message.pending");
            const lastMessage = messages[messages.length - 1];
            if (lastMessage) {
                lastMessage.remove();
            }
            addMessage("System", "Message verification failed", "error-message");
        }
    });

    // Message status (delivered/failed)
    socket.on("message_status", (data) => {
        if (data.receiver !== currentUser) return;

        const status = data.status === "delivered" ? "✓✓" : "✗";
        const messages = document.querySelectorAll(".sent-message");
        const lastMessage = messages[messages.length - 1];
        if (lastMessage) {
            lastMessage.innerHTML += ` <small>${status}</small>`;
        }
    });

    // Error handling
    socket.on("chat_error", (data) => {
        addMessage("System", data.message, "error-message");
    });

    // Connection error handling
    socket.on("connect_error", () => {
        addMessage("System", "Connection error. Please try again later.", "error-message");
    });

    socket.on("disconnect", () => {
        addMessage("System", "Disconnected from server. Trying to reconnect...", "error-message");
        sessionEstablished = false;
    });

    // Helper function to add messages to the chat
    function addMessage(sender, message, className) {
        const chat = document.querySelector("#chat-messages");
        const msgElement = document.createElement("div");
        msgElement.className = `message ${className}`;
        msgElement.innerHTML = `<strong>${sender}:</strong> ${message}`;
        chat.appendChild(msgElement);
        chat.scrollTop = chat.scrollHeight;
    }

    // Thêm hàm để xử lý các tin nhắn chưa đọc
    function loadUnreadMessages(sender) {
        // Trong một ứng dụng thực, bạn sẽ gọi API để lấy tin nhắn chưa đọc
        // Ở đây chúng ta chỉ giả lập bằng cách gửi yêu cầu đến server
        socket.emit("load_unread_messages", { sender: sender });
    }
});