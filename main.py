import logging
import os
from datetime import datetime, timedelta

import instaloader
import pyshorteners
from instaloader import Profile, Post
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

from database_functions import Database
from messages import Messages


# You will need to export the following environment variables on your env for the bot to work
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
INSTA_USERNAME = os.getenv('INSTA_USERNAME')
INSTA_PASSWORD = os.getenv('INSTA_PASSWORD')

if not all([TELEGRAM_TOKEN, INSTA_USERNAME, INSTA_PASSWORD]):
    raise ValueError('Please set the TELEGRAM_TOKEN, INSTA_USERNAME and INSTA_PASSWORD environment variables.')

# You don't want to use your own Instagram account?
# You can implement a way to get the username and password from the user and use it to login, but it will be hard :)
# Actually not only hard, but could also be a privacy problem (storing users credentials in a database)
# For that and many other reasons, I'm using my own Instagram account on this project

loader = instaloader.Instaloader()
loader.login(INSTA_USERNAME, INSTA_PASSWORD)
url_shortener = pyshorteners.Shortener()  # TODO - maybe is better to use a self-made shortener to avoid rate limits


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

class TelegramBot:
    """Telegram bot class."""

    def __init__(self, token: str):
        self.application = ApplicationBuilder().token(token).build()
        self.bot = self.application.bot
        self.database = Database()

    def register_handlers(self):
        """Registers the handlers for the bot."""
        start_handler = CommandHandler('start', self.start)
        follow_user_handle = CommandHandler('follow_user', self.follow_new_profile)
        unfollow_user_handle = CommandHandler('unfollow_user', self.unfollow_profile)
        profiles_followed_handle = CommandHandler('profiles_followed', self.get_current_profiles_followed)
        unknown_command_handler = MessageHandler(filters.ALL, self.start)

        self.application.add_handler(start_handler)
        self.application.add_handler(follow_user_handle)
        self.application.add_handler(unfollow_user_handle)
        self.application.add_handler(profiles_followed_handle)
        self.application.add_handler(unknown_command_handler)

    async def check_profiles_for_updates(self, context):
        """
        Fetches the followed profiles for the given user.
        For each profile, checks if there are new posts. If so, sends each one as a message with the video direct URL.
        To check if the posts are new, it compares the last post date stored in the database with the date of the posts.
        Updates the last_post_date value in the database for each profile.
        """
        chat_id = context.job.data
        try:
            logging.info(f'Checking for updates for user (chat_id): {chat_id}')
            followed_profiles = self.database.get_followed_profiles_from_db(chat_id)
            if not followed_profiles:
                logging.info(f'No profiles followed by user (chat_id): {chat_id}. Checking loop will stop.')
                return
            for followed_profile in followed_profiles:
                profile = Profile.from_username(loader.context, followed_profile['username'])
                # This performance heavy, as we can't filter by date in the query;
                posts = profile.get_posts()
                # Some ideas: Check only the last 10 posts, even if would mean missing some posts from time to time
                new_posts = []
                for post in posts:
                    if post.date > followed_profile['last_post_date']:
                        new_posts.append(post)
                if new_posts:
                    for post in new_posts:
                        await self.shorten_and_send_post(post, chat_id, followed_profile)
                    # Update the last post date in the database for future checking
                    self.database.update_last_post_date_in_db(chat_id, followed_profile['username'], new_posts[0].date)
                else:
                    logging.info(f"No new posts found for {followed_profile['username']}")
                # Schedule the next check
                update_interval_hours = self.database.collection.find_one({'_id': chat_id})['update_interval_hours']
                context.job_queue.run_once(self.check_profiles_for_updates, update_interval_hours * 3600, data=chat_id)
        except Exception as e:
            logging.error(f'Error checking updates: {e}')

    def get_last_post_date(self, username: str) -> datetime:
        """
        Returns the date of the most recent post of the profile.
        Pinned posts will appear first in profile.get_posts() iterator, but they aren't necessarily the most recent.
        So, we check all dates just in case.
        """
        profile = Profile.from_username(loader.context, username)
        posts = profile.get_posts()
        last_post_date = max(post.date for post in posts if not post.is_pinned)
        return last_post_date

    def start_checking_update_tasks(self) -> None:
        """Reads the database and triggers the checking update tasks for each user."""
        job_queue = self.application.job_queue
        logging.info('Starting the checking update tasks for all users')
        all_users = self.database.collection.find({})  # retrieves all documents in the collection
        for user in all_users:
            chat_id = user['_id']
            # Get update_interval_hours from the database
            update_interval_hours = self.database.collection.find_one({'_id': chat_id})['update_interval_hours']
            job_queue.run_once(self.check_profiles_for_updates, update_interval_hours * 3600, data=chat_id)

    async def shorten_and_send_post(self, post: Post, chat_id: int, followed_profile: dict) -> None:
        """Gets the link for the last post, shortens it and sends it to the Telegram bot."""
        # TODO implement GraphSidecar:
        if post.typename == 'GraphSidecar':
            message = Messages.NOT_IMPLEMENTED_YET.format(followed_profile['username'])
            await self.bot.send_message(chat_id=chat_id, text=message)
        else:
            short_url = self.shorten_url(post.url or post.video_url)
            message = Messages.NEW_POST.format(followed_profile=followed_profile, short_url=short_url)
            await self.bot.send_message(
                chat_id=chat_id,
                text=message,
            )

    def shorten_url(self, url: str) -> str:
        """Shortens a URL using the pyshorteners library."""
        try:
            short_url = url_shortener.tinyurl.short(url)
        except Exception as e:
            logging.error(f'Error shortening the URL: {e}')
            short_url = url
        return short_url

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Welcome message for the user."""
        welcome_message = Messages.WELCOME.format(
            MAX_PROFILES_PER_USER=self.database.MAX_PROFILES_PER_USER,
            DEFAULT_UPDATE_INTERVAL_HOURS=self.database.DEFAULT_UPDATE_INTERVAL_HOURS
        )
        await context.bot.send_message(chat_id=update.effective_chat.id, text=welcome_message)

    async def follow_new_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Adds a new profile to the database for the current user, which means that the user now "follows" that profile.
        Sends a message to the user with the new profile followed and some extra information.
        """
        chat_id = update.effective_chat.id
        try:
            username = context.args[0]
        except IndexError:
            message = Messages.PROVIDE_USERNAME
            await context.bot.send_message(chat_id=chat_id, text=message)
            return
        if self.database.max_profiles_for_user_reached(chat_id):
            message = Messages.MAX_PROFILES_REACHED.format(MAX_PROFILES_PER_USER=self.database.MAX_PROFILES_PER_USER)
            await context.bot.send_message(chat_id=chat_id, text=message)
            return
        if self.database.profile_is_already_followed(chat_id, username):
            message = Messages.PROFILE_ALREADY_FOLLOWED.format(username=username)
            await context.bot.send_message(chat_id=chat_id, text=message)
            return
        await context.bot.send_message(chat_id=chat_id, text='On it...')
        followed_profile = {
            'username': username,
            'last_post_date': datetime.now() - timedelta(days=4),  #  get_last_post_date(username),
        }
        self.database.add_followed_profile_to_db(chat_id, followed_profile)
        message = Messages.NEW_PROFILE_FOLLOWED.format(
            username=username,
            DEFAULT_UPDATE_INTERVAL_HOURS=self.database.DEFAULT_UPDATE_INTERVAL_HOURS
        )
        await context.bot.send_message(chat_id=chat_id, text=message)

        # Start the loop for this user. the loop will continue forever unless the user unfollows all profiles
        # It could stop if the app crashes, but it will be restarted in the __init__ method
        context.job_queue.run_once(self.check_profiles_for_updates, 0, data=chat_id)

    async def unfollow_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Stops following a profile. Removes the profile from the database."""
        chat_id = update.effective_chat.id
        try:
            username = context.args[0]
        except IndexError:
            message = Messages.PROVIDE_USERNAME_TO_UNFOLLOW
            await context.bot.send_message(chat_id=chat_id, text=message)
            return
        # If there's no user entry or the user is not following any profiles, return a message
        if any([
            self.database.collection.count_documents({'_id': chat_id}) == 0,
            self.database.collection.find_one({'_id': chat_id})['followed_profiles'] == []
        ]):
            await context.bot.send_message(chat_id=chat_id, text="You are not following any profiles.")
            return
        self.database.remove_followed_profile_from_db(chat_id, username)
        message = Messages.SUCCESS_UNFOLLOWED.format(username=username)
        await context.bot.send_message(chat_id=chat_id, text=message)

    async def get_current_profiles_followed(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Returns the list of profiles followed by the bot."""
        chat_id = update.effective_chat.id
        followed_profiles = self.database.get_followed_profiles_from_db(chat_id)
        if followed_profiles:
            message = "Profiles followed:\n"
            for profile in followed_profiles:
                message += f"- {profile['username']}\n"
        else:
            message = Messages.NO_PROFILES_FOLLOWED
        await context.bot.send_message(chat_id=chat_id, text=message)

    async def configure_update_interval(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Configures the update interval for the bot to check for new posts."""
        chat_id = update.effective_chat.id
        try:
            update_interval_hours = int(context.args[0])
        except (ValueError, IndexError):
            message = Messages.PROVIDE_NUMBER_OF_HOURS
            await context.bot.send_message(chat_id=chat_id, text=message)
            return
        self.database.update_update_interval_in_db(chat_id, update_interval_hours)
        message = Messages.UPDATE_INTERVAL_CHANGED.format(update_interval_hours=update_interval_hours)
        await context.bot.send_message(chat_id=chat_id, text=message)

    def run_polling(self):
        self.application.run_polling()


if __name__ == '__main__':
    try:
        bot = TelegramBot(TELEGRAM_TOKEN)
        bot.register_handlers()
        bot.start_checking_update_tasks()
        bot.run_polling()

    except Exception as e:
        logging.error(f'Error: {e}')
