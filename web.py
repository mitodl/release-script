"""
Web server for handling slack webhooks
"""
import json

from tornado.web import Application, RequestHandler


class ButtonHandler(RequestHandler):
    """
    Handle button requests
    """
    def initialize(self, token, bot):  # pylint: disable=arguments-differ
        """
        Set variables

        Args:
            token (str): The slack webhook token used to authenticate
            bot (Bot): The bot
        """
        # pylint: disable=attribute-defined-outside-init
        self.token = token
        self.bot = bot

    async def post(self, *args, **kwargs):  # pylint: disable=unused-argument
        """Handle webhook POST"""
        arguments = json.loads(self.get_argument("payload"))  # pylint: disable=no-value-for-parameter
        token = arguments['token']
        if token != self.token:
            self.set_status(401)
            self.finish("")
            return

        self.bot.loop.create_task(
            self.bot.handle_webhook(webhook_dict=arguments)
        )

        self.finish("")


def make_app(token, bot):
    """
    Create the application handling the webhook requests

    Args:
        token (str): The slack webhook token used to authenticate
        bot (Bot): The bot

    Returns:
        Application: A tornado application
    """
    return Application([
        (r'/api/v0/buttons/', ButtonHandler, {
            'token': token,
            'bot': bot,
        }),
    ])
