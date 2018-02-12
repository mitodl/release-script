"""
Web server for handling slack webhooks
"""
from contextlib import contextmanager
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

        self.loop.create_task(
            self.bot.handle_webhook(webhook_dict=arguments, loop=self.loop)
        )

        self.finish("")


@contextmanager
def run_web_server(*, token, bot, port, loop):
    """
    Create the application handling the webhook requests and start it

    Args:
        token (str): The slack webhook token used to authenticate
        bot (Bot): The bot
        port (int): The port number
        loop (asyncio.events.AbstractEventLoop): The event loop

    Returns:
        Application: A tornado application
    """
    app = Application([
        (r'/api/v0/buttons/', ButtonHandler, {
            'token': token,
            'bot': bot,
            'loop': loop,
        }),
    ])
    app.listen(port)
    yield app
    app.stop()
