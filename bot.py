#!/usr/bin/env python3
import os
import asyncio
import logging
from pathlib import Path
import json
from datetime import datetime
import sqlite3
import sys

from dotenv import load_dotenv

load_dotenv()

import ssl
import certifi

os.environ['SSL_CERT_FILE'] = certifi.where()
ssl._create_default_https_context = ssl._create_unverified_context

import whisper
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

try:
    import google.generativeai as genai

    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

try:
    from openai import AsyncOpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class UserAnalytics:
    def __init__(self, db_path: str = "user_analytics.db"):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    total_voice_messages INTEGER DEFAULT 0,
                    total_commands INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_activities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    activity_type TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)
            conn.commit()

    def register_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO users 
                (user_id, username, first_name, last_name, registration_date, last_activity, total_voice_messages, total_commands)
                VALUES (
                    ?, ?, ?, ?, 
                    COALESCE((SELECT registration_date FROM users WHERE user_id = ?), CURRENT_TIMESTAMP),
                    CURRENT_TIMESTAMP,
                    COALESCE((SELECT total_voice_messages FROM users WHERE user_id = ?), 0),
                    COALESCE((SELECT total_commands FROM users WHERE user_id = ?), 0)
                )
            """, (user_id, username, first_name, last_name, user_id, user_id, user_id))
            conn.commit()

    def log_activity(self, user_id: int, activity_type: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO user_activities (user_id, activity_type) VALUES (?, ?)", (user_id, activity_type))

            if activity_type == "voice_message":
                conn.execute(
                    "UPDATE users SET last_activity = CURRENT_TIMESTAMP, total_voice_messages = total_voice_messages + 1 WHERE user_id = ?",
                    (user_id,))
            elif activity_type in ["start", "help", "tips", "stats"]:
                conn.execute(
                    "UPDATE users SET last_activity = CURRENT_TIMESTAMP, total_commands = total_commands + 1 WHERE user_id = ?",
                    (user_id,))
            else:
                conn.execute("UPDATE users SET last_activity = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
            conn.commit()

    def get_user_stats(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            total_users = conn.execute("SELECT COUNT(*) as count FROM users").fetchone()['count']
            active_24h = conn.execute(
                "SELECT COUNT(*) as count FROM users WHERE last_activity >= datetime('now', '-1 day')").fetchone()[
                'count']
            active_7d = conn.execute(
                "SELECT COUNT(*) as count FROM users WHERE last_activity >= datetime('now', '-7 days')").fetchone()[
                'count']
            new_users_7d = conn.execute(
                "SELECT COUNT(*) as count FROM users WHERE registration_date >= datetime('now', '-7 days')").fetchone()[
                'count']
            total_voice = conn.execute("SELECT SUM(total_voice_messages) as total FROM users").fetchone()['total'] or 0
            total_commands = conn.execute("SELECT SUM(total_commands) as total FROM users").fetchone()['total'] or 0

            most_active = conn.execute("""
                SELECT user_id, username, first_name, total_voice_messages, total_commands
                FROM users 
                ORDER BY (total_voice_messages + total_commands) DESC 
                LIMIT 5
            """).fetchall()

            return {
                'total_users': total_users,
                'active_24h': active_24h,
                'active_7d': active_7d,
                'new_users_7d': new_users_7d,
                'total_voice_messages': total_voice,
                'total_commands': total_commands,
                'most_active_users': [dict(row) for row in most_active]
            }

    def get_user_info(self, user_id: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return dict(user) if user else None


class IELTSSpeakingBot:
    def __init__(self, telegram_token: str, ai_service: str, api_key: str):
        self.telegram_token = telegram_token
        self.ai_service = ai_service
        self.analytics = UserAnalytics()

        if ai_service == "gemini":
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
        elif ai_service == "openai":
            self.openai_client = AsyncOpenAI(api_key=api_key)

        self.whisper_model = whisper.load_model("base")
        self.downloads_dir = Path("downloads")
        self.downloads_dir.mkdir(exist_ok=True)
        self.admin_users = {8452337358}

    def register_user_from_update(self, update: Update):
        user = update.effective_user
        if user:
            self.analytics.register_user(user_id=user.id, username=user.username, first_name=user.first_name,
                                         last_name=user.last_name)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.register_user_from_update(update)
        self.analytics.log_activity(update.effective_user.id, "start")

        welcome_message = (
            "🎯 *Welcome to IELTS Speaking Practice Bot!*\n\n"
            "I'll help improve your speaking by:\n"
            "• Fixing transcription errors\n"
            "• Enhancing your natural speech\n"
            "• Showing clear improvements\n\n"
            "📤 *Just send a voice message!*\n\n"
            "What you'll get:\n"
            "✅ Corrected version\n"
            "✨ Enhanced version\n"
            "📝 Simple improvement notes\n\n"
            "Ready? Record and send! 🎤"
        )
        await update.message.reply_text(welcome_message, parse_mode='Markdown')

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.register_user_from_update(update)
        self.analytics.log_activity(update.effective_user.id, "help")

        help_text = (
            "📚 *How to Use*\n\n"
            "1. Press & hold mic 🎤\n"
            "2. Speak naturally\n"
            "3. Send voice message\n"
            "4. Get feedback!\n\n"
            "*Commands:*\n"
            "/start - Welcome\n"
            "/help - This help\n"
            "/tips - Quick tips\n"
            "/mystats - Your usage stats"
        )

        if update.effective_user.id in self.admin_users:
            help_text += "\n\n*Admin Commands:*\n/stats - Bot statistics"

        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def tips_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.register_user_from_update(update)
        self.analytics.log_activity(update.effective_user.id, "tips")

        tips_text = (
            "💡 *Speaking Tips*\n\n"
            "• Talk naturally, don't memorize\n"
            "• Use connectors (so, but, because)\n"
            "• Give real examples\n"
            "• If stuck, rephrase\n"
            "• Keep it simple\n\n"
            "Practice daily! 🎯"
        )
        await update.message.reply_text(tips_text, parse_mode='Markdown')

    async def mystats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.register_user_from_update(update)
        self.analytics.log_activity(update.effective_user.id, "mystats")

        user_info = self.analytics.get_user_info(update.effective_user.id)

        if user_info:
            reg_date = datetime.fromisoformat(user_info['registration_date']).strftime('%B %d, %Y')
            last_activity = datetime.fromisoformat(user_info['last_activity']).strftime('%B %d, %Y at %H:%M')

            stats_text = (
                f"📊 *Your Bot Statistics*\n\n"
                f"👤 **User:** {user_info['first_name'] or 'Unknown'}\n"
                f"📅 **Joined:** {reg_date}\n"
                f"🕐 **Last Activity:** {last_activity}\n\n"
                f"🎤 **Voice Messages:** {user_info['total_voice_messages']}\n"
                f"⌨️ **Commands Used:** {user_info['total_commands']}\n\n"
                f"Keep practicing! 🎯"
            )
        else:
            stats_text = "❌ No statistics found. Send a voice message to get started!"

        await update.message.reply_text(stats_text, parse_mode='Markdown')

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in self.admin_users:
            await update.message.reply_text("❌ This command is for bot administrators only.")
            return

        self.analytics.log_activity(update.effective_user.id, "admin_stats")
        stats = self.analytics.get_user_stats()

        top_users = ""
        for i, user in enumerate(stats['most_active_users'], 1):
            name = user['first_name'] or user['username'] or f"User {user['user_id']}"
            total_activity = user['total_voice_messages'] + user['total_commands']
            top_users += f"{i}. {name}: {total_activity} activities\n"

        stats_text = (
            f"📊 *Bot Analytics Dashboard*\n\n"
            f"🤖 **AI Service:** {self.ai_service.title()}\n\n"
            f"👥 **Total Users:** {stats['total_users']}\n"
            f"🟢 **Active (24h):** {stats['active_24h']}\n"
            f"🔵 **Active (7d):** {stats['active_7d']}\n"
            f"🆕 **New Users (7d):** {stats['new_users_7d']}\n\n"
            f"📈 **Usage Statistics:**\n"
            f"🎤 Total Voice Messages: {stats['total_voice_messages']}\n"
            f"⌨️ Total Commands: {stats['total_commands']}\n\n"
            f"🏆 **Most Active Users:**\n{top_users if top_users else 'No active users yet.'}"
        )

        await update.message.reply_text(stats_text, parse_mode='Markdown')

    def transcribe_audio(self, audio_path: str) -> str:
        result = self.whisper_model.transcribe(audio_path, language="en")
        return result["text"].strip()

    async def correct_and_enhance_speech(self, transcribed_text: str):
        prompt = f"""Analyze this transcribed speech. First, fix only obvious transcription errors (e.g., "mission learning" → "machine learning", "importent" → "important") to make it logical and put the dot and comma correct places and that is to make it as if it is spoken, without changing grammar, structure, or meaning. Then, create corrected(which is correction of grammer and vocab usage but in user's structure) and enhanced (the best version which helps user to bring him to next level with different structures) versions.

        TRANSCRIBED: "{transcribed_text}"

        Return ONLY this JSON (no markdown, no extra text):
        {{
            "original in voice": "The original transcribed text, fixed only for transcription errors to make it logical and readable to avoid mistakes. Keep it exactly as spoken otherwise.do not change grammar mistakes it should be done in corrected section",
            "corrected": "Version with basic grammar fixes and word corrections if they don't make sense, but preserve originality, structure, and length. Do not rewrite entirely.",
            "enhanced": "Natural improved version with better vocabulary and flow (keep similar length). Should be the best version in structure grammer and everything",
            "improvements": [ in the following structure and give the what enhance as well 
                "vocab: old → new",
                "grammar: fixed X never talk about comma or such things ",
                "flow: added Y"
                "enhanced: original in voice → enhanced (anything grammar structure or vocabulary)  "
            ]
        }}

        Keep everything natural and conversational. Limit improvements to 5-6 key items with → arrows."""

        if self.ai_service == "gemini":
            response = await asyncio.to_thread(
                self.model.generate_content,
                prompt,
                generation_config=genai.types.GenerationConfig(temperature=0.3, max_output_tokens=500)
            )
            result_text = response.text.strip()
        else:  # openai
            response = await self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are an IELTS coach. Respond only with valid JSON, no markdown."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )
            result_text = response.choices[0].message.content.strip()

        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0]
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0]

        return json.loads(result_text)

    def format_feedback(self, analysis):
        improvements = "\n".join([f"• {imp}" for imp in analysis.get('improvements', [])])

        message = (
            "🎤 *Your Speaking Analysis*\n\n"
            "📝 *Original (transcription fixed):*\n"
            f"{analysis.get('original in voice', 'N/A')}\n\n"
            "✅ *Corrected:*\n"
            f"{analysis.get('corrected', 'N/A')}\n\n"
            "✨ *Enhanced:*\n"
            f"{analysis.get('enhanced', 'N/A')}\n\n"
            "🔄 *Improvements:*\n"
            f"{improvements if improvements else '• Good job!'}"
        )
        return message

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.register_user_from_update(update)
        self.analytics.log_activity(update.effective_user.id, "voice_message")

        processing_msg = await update.message.reply_text("🎧 Processing...")

        voice_file = await update.message.voice.get_file()
        file_path = self.downloads_dir / f"voice_{update.message.message_id}.ogg"
        await voice_file.download_to_drive(file_path)

        await processing_msg.edit_text("🎯 Transcribing...")
        transcribed_text = self.transcribe_audio(str(file_path))

        if not transcribed_text or len(transcribed_text) < 10:
            await processing_msg.edit_text("❌ Couldn't hear clearly.\nTry again in a quieter place!")
            file_path.unlink(missing_ok=True)
            return

        await processing_msg.edit_text(f"✨ Enhancing...")
        analysis = await self.correct_and_enhance_speech(transcribed_text)
        feedback = self.format_feedback(analysis)
        await processing_msg.edit_text(feedback, parse_mode='Markdown')

        file_path.unlink(missing_ok=True)

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.register_user_from_update(update)
        await update.message.reply_text(
            "👋 Send a *voice message* to analyze!\nPress & hold the 🎤 button.",
            parse_mode='Markdown'
        )

    def run(self):
        application = Application.builder().token(self.telegram_token).build()

        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("tips", self.tips_command))
        application.add_handler(CommandHandler("mystats", self.mystats_command))
        application.add_handler(CommandHandler("stats", self.stats_command))
        application.add_handler(MessageHandler(filters.VOICE, self.handle_voice))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))

        logger.info(f"Bot starting with {self.ai_service} analytics...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)


def main():
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    gemini_key = os.getenv("GEMINI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if not telegram_token:
        print("❌ Missing TELEGRAM_BOT_TOKEN in .env")
        print("Get from @BotFather on Telegram")
        sys.exit(1)

    if gemini_key and GEMINI_AVAILABLE:
        ai_service, api_key = "gemini", gemini_key
        print("✅ Using Gemini AI")
    elif openai_key and OPENAI_AVAILABLE:
        ai_service, api_key = "openai", openai_key
        print("✅ Using OpenAI")
    else:
        print("❌ No AI API key found or libraries not installed!")
        print("Set either GEMINI_API_KEY or OPENAI_API_KEY in .env")
        sys.exit(1)

    print("🚀 BOT STARTED DIYORBEK")
    bot = IELTSSpeakingBot(telegram_token, ai_service, api_key)
    bot.run()


if __name__ == "__main__":
    main()