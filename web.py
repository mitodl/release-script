"""
Web server for handling slack webhooks
"""
import hmac
import json

from tornado.web import Application, RequestHandler


def is_authenticated(request, secret):
    """
    Verify whether the user is authenticated

    Args:
        request (tornado.httputil.HTTPRequest): The request
        secret (str): The secret to use for authentication
    """
    # See https://api.slack.com/authentication/verifying-requests-from-slack for more info
    timestamp = request.headers["X-Slack-Request-Timestamp"]
    basestring = f"v0:{timestamp}:{request.body.decode()}".encode()
    digest = (
        "v0="
        + hmac.new(key=secret.encode(), msg=basestring, digestmod="sha256").hexdigest()
    ).encode()
    signature = request.headers["X-Slack-Signature"].encode()
    return hmac.compare_digest(digest, signature)


class ButtonHandler(RequestHandler):
    """
    Handle button requests
    """

    def initialize(self, secret, bot):  # pylint: disable=arguments-differ
        """
        Set variables

        Args:
            secret (str): The slack signing secret token used to authenticate
            bot (Bot): The bot
        """
        # pylint: disable=attribute-defined-outside-init
        self.secret = secret
        self.bot = bot

    async def post(self, *args, **kwargs):  # pylint: disable=unused-argument
        """Handle webhook POST"""
        if not is_authenticated(self.request, self.secret):
            self.set_status(401)
            await self.finish("")
            return

        arguments = json.loads(
            self.get_argument("payload")
        )  # pylint: disable=no-value-for-parameter
        self.bot.loop.create_task(self.bot.handle_webhook(webhook_dict=arguments))
        await self.finish("")


class EventHandler(RequestHandler):
    """Handle events from Slack's events API"""

    def initialize(self, secret, bot):  # pylint: disable=arguments-differ
        """
        Set variables

        Args:
            secret (str): The slack signing secret token used to authenticate
            bot (Bot): The bot
        """
        # pylint: disable=attribute-defined-outside-init
        self.secret = secret
        self.bot = bot

    async def post(self, *args, **kwargs):  # pylint: disable=unused-argument
        """Handle webhook POST"""
        if not is_authenticated(self.request, self.secret):
            self.set_status(401)
            await self.finish("")
            return

        arguments = json.loads(self.request.body)
        request_type = arguments["type"]
        if request_type == "url_verification":
            challenge = arguments["challenge"]
            await self.finish(challenge)
            return

        self.bot.loop.create_task(self.bot.handle_event(webhook_dict=arguments))

        await self.finish("")


def make_app(*, secret, bot):
    """
    Create the application handling the webhook requests

    Args:
        secret (str): The slack secret used to authenticate
        bot (Bot): The bot

    Returns:
        Application: A tornado application
    """
    return Application(
        [
            (r"/api/v0/buttons/", ButtonHandler, {"secret": secret, "bot": bot,}),
            (r"/api/v0/events/", EventHandler, {"secret": secret, "bot": bot,}),
        ]
    )
