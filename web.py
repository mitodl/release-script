"""
Web server for handling slack webhooks
"""
import json

from tornado.web import Application, RequestHandler


class ButtonHandler(RequestHandler):
    """
    Handle button requests
    """
    def initialize(self, token, bot, repos_info, loop):  # pylint: disable=arguments-differ
        """
        Set variables

        Args:
            token (str): The slack webhook token used to authenticate
            bot (Bot): The bot
            repos_info (list of RepoInfo): Information about repositories and their Slack channels
            loop (asyncio.events.AbstractEventLoop): The event loop
        """
        self.token = token
        self.bot = bot
        self.repos_info = repos_info
        self.loop = loop

    async def post(self, *args, **kwargs):
        """Handle webhook POST"""
        arguments = json.loads(self.get_argument("payload"))
        token = arguments['token']
        if token != self.token:
            self.set_status(401)
            self.finish("")
            return

        channel_id = arguments['channel']['id']
        user_id = arguments['user']['id']
        callback_id = arguments['callback_id']
        channel_repo_info = None
        for repo_info in self.repos_info:
            if repo_info.channel_id == channel_id:
                channel_repo_info = repo_info

        self.loop.create_task(self.bot.handle_webhook(
            channel_id=channel_id,
            user_id=user_id,
            repo_info=channel_repo_info,
            callback_id=callback_id,
        ))

        self.finish("")


def make_app(token, bot, repos_info, loop):
    """
    Create the application handling the webhook requests

    Args:
        token (str): The slack webhook token used to authenticate
        bot (Bot): The bot
        repos_info (list of RepoInfo): Information about repositories and their Slack channels
        loop (asyncio.events.AbstractEventLoop): The event loop

    Returns:
        Application: A tornado application
    """
    return Application([
        (r'/api/v0/buttons/', ButtonHandler, {
            'token': token,
            'bot': bot,
            'repos_info': repos_info,
            'loop': loop,
        }),
    ])
