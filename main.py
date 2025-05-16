import logging
import os
from datetime import datetime, timedelta

import instaloader
import pyshorteners
from instaloader import Profile, Post
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

from database_functions import update_last_post_date_in_db, get_followed_profiles_from_db, \
    remove_followed_profile_from_db, update_update_interval_in_db, profile_is_already_followed, \
    add_followed_profile_to_db, MAX_PROFILES_PER_USER, DEFAULT_UPDATE_INTERVAL_HOURS, collection, \
    max_profiles_for_user_reached


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


async def check_profiles_for_updates(context):
    """
    Fetches the followed profiles for the given user.
    For each profile, checks if there are new posts. If so, sends each one as a message with the video direct URL.
    To check if the posts are new, it compares the last post date stored in the database with the date of the posts.
    Updates the last_post_date value in the database for each profile.
    """
    chat_id = context.job.data
    try:
        logging.info(f'Checking for updates for user (chat_id): {chat_id}')
        followed_profiles = get_followed_profiles_from_db(chat_id)
        if not followed_profiles:
            logging.info(f'No profiles followed by user (chat_id): {chat_id}. Checking loop will stop.')
            return
        for followed_profile in followed_profiles:
            logging.info('Followed profiles found. Checking posts dates')
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
                    await shorten_and_send_post(post, chat_id, followed_profile)
                # Update the last post date in the database for future checking
                update_last_post_date_in_db(chat_id, followed_profile['username'], new_posts[0].date)
            else:
                logging.info(f"No new posts found for {followed_profile['username']}")
            # Schedule the next check
            update_interval_hours = collection.find_one({'_id': chat_id})['update_interval_hours']
            context.job_queue.run_once(check_profiles_for_updates, update_interval_hours * 3600, data=chat_id)
    except Exception as e:
        logging.error(f'Error checking updates: {e}')


def get_last_post_date(username):
    """
    Returns the date of the most recent post of the profile.
    Pinned posts will appear first in profile.get_posts() iterator, but they aren't necessarily the most recent.
    So, we check all dates just in case.
    """
    profile = Profile.from_username(loader.context, username)
    posts = profile.get_posts()
    last_post_date = max(post.date for post in posts if not post.is_pinned)
    return last_post_date


def start_checking_update_tasks() -> None:
    """Reads the database and triggers the checking update tasks for each user."""
    job_queue = application.job_queue
    logging.info('Starting the checking update tasks for all users')
    all_users = collection.find({})  # retrieves all documents in the collection
    for user in all_users:
        chat_id = user['_id']
        # Get update_interval_hours from the database
        update_interval_hours = collection.find_one({'_id': chat_id})['update_interval_hours']
        job_queue.run_once(check_profiles_for_updates, update_interval_hours * 3600, data=chat_id)


async def shorten_and_send_post(post: Post, chat_id: int, followed_profile: dict) -> None:
    """Gets the link for the last post, shortens it and sends it to the Telegram bot."""
    global bot  # TODO is this necessary? Can I improve it?
    # TODO implement GraphSidecar:
    if post.typename == 'GraphSidecar':
        message = f"{followed_profile['username']} uploaded a new post, but I can't display Posts with multiple media yet :("
        await bot.send_message(chat_id=chat_id, text=message)
    else:
        try:
            short_url = url_shortener.tinyurl.short(post.video_url or post.url)
        except Exception as shortener_error:
            logging.error(f'Error shortening the URL: {shortener_error}')
            short_url = post.url
        message = f"New post from {followed_profile['username']}: {short_url}"
        await bot.send_message(
            chat_id=chat_id,
            text=message,
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message for the user."""
    welcome_message = f'''
    🤖 Welcome to this Instagram feed bot! (sorry for the uncool name)\n
    - Use /follow_user USERNAME to start following an instagram profile. You can follow up to {MAX_PROFILES_PER_USER} profiles.\n
    - Use /unfollow_user USERNAME to stop following a profile.\n
    - Use /profiles_followed to see the profiles you are following.\n
    - Use /configure_update_interval HOURS to change the frequency for checking updates. Default is {DEFAULT_UPDATE_INTERVAL_HOURS} hours.\n
    '''
    await context.bot.send_message(chat_id=update.effective_chat.id, text=welcome_message)


async def follow_new_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Adds a new profile to the database for the current user, which means that the user now "follows" that profile.
    Sends a message to the user with the new profile followed and some extra information.
    """
    chat_id = update.effective_chat.id
    try:
        username = context.args[0]
    except IndexError:
        message = '⚠️ Please provide the username, for example: /follow_user PedroPascal20'
        await context.bot.send_message(chat_id=chat_id, text=message)
        return
    if max_profiles_for_user_reached(chat_id):
        message = f'Sorry, you can only follow up to {MAX_PROFILES_PER_USER} profiles.'
        await context.bot.send_message(chat_id=chat_id, text=message)
        return
    if profile_is_already_followed(chat_id, username):
        message = f'You are already following {username}'
        await context.bot.send_message(chat_id=chat_id, text=message)
        return
    await context.bot.send_message(chat_id=chat_id, text='On it...')
    followed_profile = {
        'username': username,
        'last_post_date': datetime.now() - timedelta(days=4),  #  get_last_post_date(username),
    }
    add_followed_profile_to_db(chat_id, followed_profile)
    message = f'''
    New profile followed: {username}\n
    - The update interval for the bot is {DEFAULT_UPDATE_INTERVAL_HOURS} hours. To change it, use /configure_update_interval.\n
    - You won't see any new posts right now, but after the next check in that time.
    '''
    await context.bot.send_message(chat_id=chat_id, text=message)

    # Start the loop for this user. the loop will continue forever unless the user unfollows all profiles
    # It could stop if the app crashes, but it will be restarted in the __init__ method
    context.job_queue.run_once(check_profiles_for_updates, 0, data=chat_id)


async def unfollow_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stops following a profile. Removes the profile from the database."""
    chat_id = update.effective_chat.id
    try:
        username = context.args[0]
    except IndexError:
        message = '⚠️ Please provide the username, for example: /unfollow_user PedroPascal20'
        await context.bot.send_message(chat_id=chat_id, text=message)
        return
    # If there's no user entry or the user is not following any profiles, return a message
    if collection.count_documents({'_id': chat_id}) == 0 or collection.find_one({'_id': chat_id})['followed_profiles'] == []:
        await context.bot.send_message(chat_id=chat_id, text="You are not following any profiles.")
        return
    remove_followed_profile_from_db(chat_id, username)
    message = f'Profile {username} removed from the followed profiles.'
    await context.bot.send_message(chat_id=chat_id, text=message)


async def get_current_profiles_followed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Returns the list of profiles followed by the bot."""
    chat_id = update.effective_chat.id
    followed_profiles = get_followed_profiles_from_db(chat_id)
    if followed_profiles:
        message = "Profiles followed:\n"
        for profile in followed_profiles:
            message += f"- {profile['username']}\n"
    else:
        message = "No profiles followed"
    await context.bot.send_message(chat_id=chat_id, text=message)


async def configure_update_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Configures the update interval for the bot to check for new posts."""
    chat_id = update.effective_chat.id
    try:
        update_interval_hours = int(context.args[0])
    except (ValueError, IndexError):
        message = '⚠️ Please use the command with a number, for example: "/configure_update_interval 4".'
        await context.bot.send_message(chat_id=chat_id, text=message)
        return
    update_update_interval_in_db(chat_id, update_interval_hours)
    message = f'Update interval configured to: {update_interval_hours} hours'
    await context.bot.send_message(chat_id=chat_id, text=message)


if __name__ == '__main__':
    try:
        application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        bot = application.bot

        # Define handlers
        start_handler = CommandHandler('start', start)
        follow_user_handle = CommandHandler('follow_user', follow_new_profile)
        unfollow_user_handle = CommandHandler('unfollow_user', unfollow_profile)
        configure_update_interval = CommandHandler('configure_update_interval', configure_update_interval)
        profiles_followed_handle = CommandHandler('profiles_followed', get_current_profiles_followed)
        # filters.ALL takes all the remaining messages that are not recognized as valid commands
        unknown_command_handler = MessageHandler(filters.ALL, start)

        # Add handlers to the application
        application.add_handler(start_handler)
        application.add_handler(follow_user_handle)
        application.add_handler(unfollow_user_handle)
        application.add_handler(configure_update_interval)
        application.add_handler(profiles_followed_handle)
        application.add_handler(unknown_command_handler)

        # Trigger the initial update checking for all users
        start_checking_update_tasks()

        application.run_polling()

    except Exception as e:
        logging.error(f'Error: {e}')
