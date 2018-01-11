"""
Web server for handling slack webhooks
"""
import json

from tornado.web import Application, RequestHandler

from exception import TokenException


class ButtonHandler(RequestHandler):
    """
    Handle button requests
    """
    def initialize(self, token, bot, repos_info):  # pylint: disable=arguments-differ
        """Set variables"""
        self.token = token
        self.bot = bot
        self.repos_info = repos_info

    async def post(self, *args, **kwargs):
        arguments = json.loads(self.get_argument("payload"))
        token = arguments['token']
        if token != self.token:
            raise TokenException()

        channel_id = arguments['channel']['id']
        channel_repo_info = None
        for repo_info in self.repos_info:
            if repo_info.channel_id == channel_id:
                channel_repo_info = repo_info

        await self.bot.handle_webhook(channel_id, channel_repo_info, arguments)

        self.finish("")


def make_app(token, bot, repos_info, port=8999):
    """Create the application handling the webhook requests"""
    app = Application([
        (r'/api/v0/buttons/', ButtonHandler, {'token': token, 'bot': bot, 'repos_info': repos_info}),
    ])
    app.listen(port)
    return app
