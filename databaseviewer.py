import sqlite3
import pandas as pd
from datetime import datetime


def view_bot_database(db_path="user_analytics.db"):

    try:
        conn = sqlite3.connect(db_path)

        print("🗃️  Bot Database Analytics")
        print("=" * 50)

        # Users table
        print("\n👥 USERS TABLE:")
        users_df = pd.read_sql_query("SELECT * FROM users ORDER BY registration_date DESC", conn)
        if not users_df.empty:
            print(f"Total users: {len(users_df)}")
            print("\nRecent users:")
            print(users_df[['user_id', 'username', 'first_name', 'registration_date', 'total_voice_messages']].head(
                10).to_string(index=False))
        else:
            print("No users found.")

        # Activities table
        print("\n\n📊 RECENT ACTIVITIES:")
        activities_df = pd.read_sql_query("""
            SELECT u.first_name, u.username, a.activity_type, a.timestamp 
            FROM user_activities a 
            JOIN users u ON a.user_id = u.user_id 
            ORDER BY a.timestamp DESC 
            LIMIT 20
        """, conn)

        if not activities_df.empty:
            print(activities_df.to_string(index=False))
        else:
            print("No activities found.")

        # Statistics
        print("\n\n📈 STATISTICS:")
        stats = conn.execute("""
            SELECT 
                COUNT(*) as total_users,
                SUM(total_voice_messages) as total_voice,
                SUM(total_commands) as total_commands,
                COUNT(CASE WHEN last_activity >= datetime('now', '-1 day') THEN 1 END) as active_24h,
                COUNT(CASE WHEN last_activity >= datetime('now', '-7 days') THEN 1 END) as active_7d
            FROM users
        """).fetchone()

        print(f"Total Users: {stats[0]}")
        print(f"Total Voice Messages: {stats[1] or 0}")
        print(f"Total Commands: {stats[2] or 0}")
        print(f"Active (24h): {stats[3]}")
        print(f"Active (7d): {stats[4]}")

        conn.close()

    except Exception as e:
        print(f"Error reading database: {e}")
        print("Make sure the bot has run at least once to create the database.")


def export_users_csv(db_path="user_analytics.db", output_file="bot_users.csv"):
    """Export users to CSV file."""
    try:
        conn = sqlite3.connect(db_path)
        users_df = pd.read_sql_query("SELECT * FROM users", conn)
        users_df.to_csv(output_file, index=False)
        print(f"✅ Users exported to {output_file}")
        conn.close()
    except Exception as e:
        print(f"Error exporting: {e}")


if __name__ == "__main__":
    view_bot_database()
