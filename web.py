"""
Web server for handling slack webhooks
"""
import json

from tornado.web import Application, RequestHandler


class ButtonHandler(RequestHandler):
    """
    Handle button requests
    """
    def initialize(self, token, bot, loop):  # pylint: disable=arguments-differ
        """
        Set variables

        Args:
            token (str): The slack webhook token used to authenticate
            bot (Bot): The bot
            loop (asyncio.events.AbstractEventLoop): The event loop
        """
        self.token = token
        self.bot = bot
        self.loop = loop

    async def post(self, *args, **kwargs):
        """Handle webhook POST"""
        arguments = json.loads(self.get_argument("payload"))
        token = arguments['token']
        if token != self.token:
            self.set_status(401)
            self.finish("")
            return

        print("here")
        self.loop.create_task(
            self.bot.handle_webhook(webhook_dict=arguments, loop=self.loop)
        )

        self.finish("")


def make_app(token, bot, loop):
    """
    Create the application handling the webhook requests

    Args:
        token (str): The slack webhook token used to authenticate
        bot (Bot): The bot
        loop (asyncio.events.AbstractEventLoop): The event loop

    Returns:
        Application: A tornado application
    """
    return Application([
        (r'/api/v0/buttons/', ButtonHandler, {
            'token': token,
            'bot': bot,
            'loop': loop,
        }),
    ])
