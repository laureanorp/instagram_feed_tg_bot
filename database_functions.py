from pymongo import MongoClient


class Database:
    """Class to handle the database operations for the Telegram bot."""
    MAX_PROFILES_PER_USER = 5  # how many profiles can a user follow
    DEFAULT_UPDATE_INTERVAL_HOURS = 4  # how often the bot checks for new posts

    def __init__(self):
        self.client = MongoClient('mongodb://localhost:27017/')
        self.db = self.client['telegram_instagra_feed_bot']
        self.collection = self.db['user_data']

    def add_followed_profile_to_db(self, chat_id, followed_profile):
        """Adds a new followed profile to the database, for a user (chat_id)."""
        # Check if the chat_id already exists in the collection
        if self.collection.count_documents({'_id': chat_id}) == 0:
            # If not, create a new document with the chat_id and followed profiles
            self.collection.insert_one({'_id': chat_id, 'followed_profiles': [followed_profile], 'update_interval_hours': self.DEFAULT_UPDATE_INTERVAL_HOURS})
        else:
            # If it exists, update the existing document to add the new followed profile
            self.collection.update_one({'_id': chat_id}, {'$addToSet': {'followed_profiles': followed_profile}})

    def remove_followed_profile_from_db(self, chat_id, username):
        """Removes a followed profile from the database"""
        self.collection.update_one({'_id': chat_id}, {'$pull': {'followed_profiles': {'username': username}}})

    def update_last_post_date_in_db(self, chat_id, username, last_post_date):
        """Updates the last_post_date for a followed profile in the database."""
        self.collection.update_one(
            {'_id': chat_id, 'followed_profiles.username': username},
            {'$set': {'followed_profiles.$.last_post_date': last_post_date}}
        )

    def update_update_interval_in_db(self, chat_id, update_interval_hours):
        """Updates the update interval for the bot to check for new posts."""
        if self.collection.count_documents({'_id': chat_id}) == 0:
            # If not, create a new document with the chat_id and followed profiles
            self.collection.insert_one({'_id': chat_id, 'followed_profiles': [], 'update_interval_hours': update_interval_hours})
        else:
            self.collection.update_one({'_id': chat_id}, {'$set': {'update_interval_hours': update_interval_hours}})

    def get_followed_profiles_from_db(self, chat_id):
        """Returns the list of followed profiles for the given user (chat_id)."""
        document = self.collection.find_one({'_id': chat_id})
        if document:
            return document['followed_profiles']
        else:
            return []

    def max_profiles_for_user_reached(self, chat_id):
        """Checks if the user has reached the maximum number of profiles followed."""
        document = self.collection.find_one({'_id': chat_id})
        if document:
            return len(document['followed_profiles']) >= self.MAX_PROFILES_PER_USER
        else:
            return False

    def profile_is_already_followed(self, chat_id, username):
        """Checks if the profile is already being followed by the user."""
        document = self.collection.find_one({'_id': chat_id})
        if document:
            for profile in document['followed_profiles']:
                if profile['username'] == username:
                    return True
        return False


