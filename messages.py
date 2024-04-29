class Messages:
    WELCOME = """
        🤖 Welcome to this Instagram feed bot! (sorry for the uncool name)\n
        - Use /follow_user USERNAME to start following an instagram profile. You can follow up to {MAX_PROFILES_PER_USER} profiles.\n
        - Use /unfollow_user USERNAME to stop following a profile.\n
        - Use /profiles_followed to see the profiles you are following.\n
        - Use /configure_update_interval HOURS to change the frequency for checking updates. Default is {DEFAULT_UPDATE_INTERVAL_HOURS} hours.\n
        """
    NOT_IMPLEMENTED_YET = "{followed_profile['username']} uploaded a new post, but I can't display Posts with multiple media yet :("
    NEW_POST = "New post from {followed_profile['username']}: {short_url}"
    PROVIDE_USERNAME = "⚠️ Please provide the username, for example: /follow_user PedroPascal20"
    MAX_PROFILES_REACHED = "Sorry, you can only follow up to {MAX_PROFILES_PER_USER} profiles."
    PROFILE_ALREADY_FOLLOWED = "You are already following {username}"
    NEW_PROFILE_FOLLOWED = """
        New profile followed: {username}\n
        - The update interval for the bot is {DEFAULT_UPDATE_INTERVAL_HOURS} hours. To change it, use /configure_update_interval.\n
        - You won't see any new posts right now, but after the next check in that time.
        """
    PROVIDE_USERNAME_TO_UNFOLLOW = "⚠️ Please provide the username, for example: /unfollow_user PedroPascal20"
    SUCCESS_UNFOLLOWED = "Profile {username} removed from the followed profiles."
    NO_PROFILES_FOLLOWED = "You are not following any profiles yet."
    PROVIDE_NUMBER_OF_HOURS = "⚠️ Please use the command with a number, for example: '/configure_update_interval 4'."
    UPDATE_INTERVAL_CHANGED = "Update interval configured to: {update_interval_hours} hours"
