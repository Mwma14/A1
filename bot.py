
import os
import sqlite3
import logging
from datetime import datetime
import gdown
from dotenv import load_dotenv  # <--- ADD THIS LINE

# Load variables from .env file
load_dotenv()  # <--- ADD THIS LINE
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.error import TelegramError

# --- Setup Logging ---
# Enable logging to see errors
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Constants ---
# Get bot token from environment variable
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    print("Error: BOT_TOKEN environment variable not set.")
    exit(1)

# Database file name
DB_FILE = "videos.db"

# States for ConversationHandler
GET_LINK = 0

# --- Database Functions ---

def setup_database():
    """Creates the database and the 'videos' table if they don't exist."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                original_link TEXT NOT NULL,
                telegram_file TEXT,
                status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
        logger.info(f"Database '{DB_FILE}' initialized successfully.")
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
    finally:
        if conn:
            conn.close()


def log_to_db(user_id, original_link, telegram_file_id, status):
    """Logs a conversion attempt to the SQLite database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO videos (user_id, original_link, telegram_file, status)
            VALUES (?, ?, ?, ?)
            """,
            (str(user_id), original_link, telegram_file_id, status),
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Failed to log to database: {e}")
    finally:
        if conn:
            conn.close()


# --- Bot Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    await update.message.reply_text(
        "Hi! I can convert Google Drive video links into Telegram videos.\n\n"
        "Send /convertvd to start."
    )


async def convert_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the conversion conversation."""
    await update.message.reply_text("Please send your Google Drive video link 👇")
    return GET_LINK


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the Google Drive link, downloads, uploads, and cleans up."""
    link = update.message.text
    user_id = update.message.from_user.id
    output_path = None  # To store the downloaded file path

    # 1. Validate Link
    if "drive.google.com" not in link:
        await update.message.reply_text(
            "⚠️ This doesn't look like a valid Google Drive link. "
            "Please check the link and try /convertvd again."
        )
        return ConversationHandler.END

    status_msg = await update.message.reply_text("⏳ Downloading video...")

    try:
        # 2. Download Video using gdown
        # 'fuzzy=True' helps gdown extract the file ID from various GDrive URL formats
        output_path = gdown.download(link, quiet=False, fuzzy=True)

        if output_path is None:
            # --- MODIFICATION 1: Changed the exception type ---
            raise Exception("Download failed. File might be private or deleted.")

        # 3. Upload to Telegram
        await status_msg.edit_text("📤 Uploading to Telegram...")
        
        with open(output_path, "rb") as video_file:
            sent_video = await update.message.reply_video(
                video=video_file,
                supports_streaming=True
            )
        
        # 4. Log Success to DB
        telegram_file_id = sent_video.video.file_id
        log_to_db(user_id, link, telegram_file_id, "done")

        # 5. Send Final Message
        await status_msg.edit_text("✅ Upload complete!")

    # --- MODIFICATION 2: Removed the buggy gdown.exceptions.DownloadError block ---
    # (The block that was here from lines 145-148 is now gone)
        
    except TelegramError as e:
        logger.error(f"Telegram upload error: {e}")
        # Handle file too large error specifically
        if "File is too big" in str(e):
            await status_msg.edit_text(
                "❌ Error: The video file is too large for me to upload to Telegram (max 2GB)."
            )
        # --- ADDED: Handle the TimedOut error you saw in your logs ---
        elif "Timed out" in str(e):
             await status_msg.edit_text(
                "❌ Error: The upload to Telegram timed out. This can happen with large files or network issues. Please try again."
            )
        else:
            await status_msg.edit_text(f"❌ An error occurred during upload: {e}")
        log_to_db(user_id, link, None, "error")

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        # This will now correctly catch the "Download failed" error from above
        await status_msg.edit_text(f"❌ An unexpected error occurred: {e}")
        log_to_db(user_id, link, None, "error")

    finally:
        # 6. Delete Local File
        if output_path and os.path.exists(output_path):
            try:
                os.remove(output_path)
                logger.info(f"Successfully deleted local file: {output_path}")
            except OSError as e:
                logger.error(f"Error deleting file {output_path}: {e}")

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the current operation."""
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END


# --- Main Bot Setup ---

def main():
    """Run the bot."""
    # Run the database setup function on start
    setup_database()

    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Create the ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("convertvd", convert_start)],
        states={
            GET_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Add handlers to the application
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start_command))

    # Run the bot
    print("Bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()
