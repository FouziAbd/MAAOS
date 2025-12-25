import sqlite3
import json


class History:
    """
    This class is responsible for maintaining history of actions, belief states,
    models, and reward functions using a SQL DB.
    """

    def __init__(self, db_path="agent_history.db"):
        """
        Initialize the database connection and create tables if they don't exist.
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        # Allow accessing columns by name (row['action'])
        self.conn.row_factory = sqlite3.Row
        self._create_table()

    def _create_table(self):
        """
        Creates the main history table.
        We use TEXT for complex fields to store them as JSON strings.
        """
        query = """
                CREATE TABLE IF NOT EXISTS history \
                ( \
                    id \
                    INTEGER \
                    PRIMARY \
                    KEY \
                    AUTOINCREMENT, \
                    timestamp \
                    DATETIME \
                    DEFAULT \
                    CURRENT_TIMESTAMP, \
                    action \
                    TEXT, \
                    belief_state \
                    TEXT, \
                    model_metadata \
                    TEXT, \
                    reward_function \
                    TEXT
                ); \
                """
        with self.conn:
            self.conn.execute(query)

    def log_step(self, action, belief_state, model_metadata=None, reward_function=None):
        """
        Logs a single step or event into the database.
        Complex objects (dicts/lists) are automatically converted to JSON strings.
        """
        query = """
                INSERT INTO history (action, belief_state, model_metadata, reward_function)
                VALUES (?, ?, ?, ?) \
                """

        # Serialize inputs to JSON if they are not strings/None
        # This ensures dicts/lists are stored safely
        action_json = self._serialize(action)
        belief_json = self._serialize(belief_state)
        model_json = self._serialize(model_metadata)
        reward_json = self._serialize(reward_function)

        with self.conn:
            self.conn.execute(query, (action_json, belief_json, model_json, reward_json))

    def get_recent_history(self, limit=10):
        """
        Retrieves the last N entries from the history.
        Deserializes JSON strings back into Python objects.
        """
        query = "SELECT * FROM history ORDER BY id DESC LIMIT ?"
        cursor = self.conn.execute(query, (limit,))
        rows = cursor.fetchall()

        history_data = []
        for row in rows:
            entry = {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "action": self._deserialize(row["action"]),
                "belief_state": self._deserialize(row["belief_state"]),
                "model_metadata": self._deserialize(row["model_metadata"]),
                "reward_function": self._deserialize(row["reward_function"]),
            }
            history_data.append(entry)

        # Return reversed so it is chronological (oldest -> newest)
        return history_data[::-1]

    def _serialize(self, data):
        """Helper to dump data to JSON, handling None safely."""
        if data is None:
            return None
        return json.dumps(data)

    def _deserialize(self, data):
        """Helper to load JSON data, returning original string if parsing fails."""
        if data is None:
            return None
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return data

    def close(self):
        """Closes the database connection."""
        self.conn.close()


# --- Example Usage ---
if __name__ == "__main__":
    # 1. Initialize
    history_db = History("agent_history.db")

    # 2. Mock Data (e.g., from an RL agent)
    action_taken = {"type": "move", "coordinates": [10, 20]}
    current_belief = {"confidence": 0.85, "suspected_location": "room_A"}

    # 3. Log the step
    history_db.log_step(
        action=action_taken,
        belief_state=current_belief,
        reward_function="standard_euclidean_distance"
    )

    # 4. Retrieve and print
    records = history_db.get_recent_history(1)
    print("Last Record:", records[0])

    # 5. Cleanup
    history_db.close()