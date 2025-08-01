"""
Models for notifications
"""
import logging
from typing import Dict

from django.contrib.auth import get_user_model
from django.db import models
from model_utils.models import TimeStampedModel
from opaque_keys.edx.django.models import CourseKeyField

from openedx.core.djangoapps.notifications.base_notification import (
    NotificationAppManager,
    NotificationPreferenceSyncManager,
    get_notification_content
)
from openedx.core.djangoapps.notifications.email import ONE_CLICK_EMAIL_UNSUB_KEY
from openedx.core.djangoapps.notifications.email_notifications import EmailCadence
from openedx.core.djangoapps.user_api.models import UserPreference

User = get_user_model()
log = logging.getLogger(__name__)

NOTIFICATION_CHANNELS = ['web', 'push', 'email']

ADDITIONAL_NOTIFICATION_CHANNEL_SETTINGS = ['email_cadence']

# Update this version when there is a change to any course specific notification type or app.
COURSE_NOTIFICATION_CONFIG_VERSION = 15


def get_course_notification_preference_config():
    """
    Returns the course specific notification preference config.

    Sample Response:
    {
        'discussion': {
            'enabled': True,
            'not_editable': {
                'new_comment_on_post': ['push'],
                'new_response_on_post': ['web'],
                'new_response_on_comment': ['web', 'push']
            },
            'notification_types': {
                'new_comment_on_post': {
                    'email': True,
                    'push': True,
                    'web': True,
                    'info': 'Comment on post'
                },
                'new_response_on_comment': {
                    'email': True,
                    'push': True,
                    'web': True,
                    'info': 'Response on comment'
                },
                'new_response_on_post': {
                    'email': True,
                    'push': True,
                    'web': True,
                    'info': 'New Response on Post'
                },
                'core': {
                    'email': True,
                    'push': True,
                    'web': True,
                    'info': 'comment on post and response on comment'
                }
            },
            'core_notification_types': []
        }
    }
    """
    return NotificationAppManager().get_notification_app_preferences()


def get_course_notification_preference_config_version():
    """
    Returns the notification preference config version.
    """
    return COURSE_NOTIFICATION_CONFIG_VERSION


def get_notification_channels():
    """
    Returns the notification channels.
    """
    return NOTIFICATION_CHANNELS


def get_additional_notification_channel_settings():
    """
    Returns the additional notification channel settings.
    """
    return ADDITIONAL_NOTIFICATION_CHANNEL_SETTINGS


class Notification(TimeStampedModel):
    """
    Model to store notifications for users

    .. no_pii:
    """
    user = models.ForeignKey(User, related_name="notifications", on_delete=models.CASCADE)
    course_id = CourseKeyField(max_length=255, null=True, blank=True)
    app_name = models.CharField(max_length=64, db_index=True)
    notification_type = models.CharField(max_length=64)
    content_context = models.JSONField(default=dict)
    content_url = models.URLField(null=True, blank=True)
    web = models.BooleanField(default=True, null=False, blank=False)
    email = models.BooleanField(default=False, null=False, blank=False)
    push = models.BooleanField(default=False, null=False, blank=False)
    last_read = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    group_by_id = models.CharField(max_length=255, db_index=True, null=False, default="")

    def __str__(self):
        return f'{self.user.username} - {self.course_id} - {self.app_name} - {self.notification_type}'

    @property
    def content(self):
        """
        Returns the content for the notification.
        """
        return get_notification_content(self.notification_type, self.content_context)


class NotificationPreference(TimeStampedModel):
    """
    Model to store notification preferences for users at account level
    """

    class EmailCadenceChoices(models.TextChoices):
        DAILY = 'Daily'
        WEEKLY = 'Weekly'
        IMMEDIATELY = 'Immediately'

    class Meta:
        # Ensures user do not have duplicate preferences.
        unique_together = ('user', 'app', 'type',)

    user = models.ForeignKey(User, related_name="notification_preference", on_delete=models.CASCADE)
    type = models.CharField(max_length=128, db_index=True)
    app = models.CharField(max_length=128, null=False, blank=False, db_index=True)
    web = models.BooleanField(default=True, null=False, blank=False)
    push = models.BooleanField(default=False, null=False, blank=False)
    email = models.BooleanField(default=False, null=False, blank=False)
    email_cadence = models.CharField(max_length=64, choices=EmailCadenceChoices.choices, null=False, blank=False)
    is_active = models.BooleanField(default=True)

    def is_enabled_for_any_channel(self, *args, **kwargs) -> bool:
        """
        Returns True if the notification preference is enabled for any channel.
        """
        return self.web or self.push or self.email

    def get_channels_for_notification_type(self, *args, **kwargs) -> list:
        """
        Returns the channels for the given app name and notification type.
        Sample Response:
        ['web', 'push']
        """
        channels = []
        if self.web:
            channels.append('web')
        if self.push:
            channels.append('push')
        if self.email:
            channels.append('email')
        return channels

    def get_email_cadence_for_notification_type(self, *args, **kwargs) -> str:
        """
        Returns the email cadence for the notification type.
        """
        return self.email_cadence


class CourseNotificationPreference(TimeStampedModel):
    """
    Model to store notification preferences for users

    .. no_pii:
    """
    user = models.ForeignKey(User, related_name="notification_preferences", on_delete=models.CASCADE)
    course_id = CourseKeyField(max_length=255, null=False, blank=False)
    notification_preference_config = models.JSONField(default=get_course_notification_preference_config)
    # This version indicates the current version of this notification preference.
    config_version = models.IntegerField(default=get_course_notification_preference_config_version)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('user', 'course_id')

    def __str__(self):
        return f'{self.user.username} - {self.course_id}'

    @staticmethod
    def get_user_course_preference(user_id, course_id):
        """
        Returns updated courses preferences for a user
        """
        email_opt_out = False
        try:
            preferences = CourseNotificationPreference.objects.get(user_id=user_id, course_id=course_id, is_active=True)
        except CourseNotificationPreference.DoesNotExist:
            email_opt_out = UserPreference.objects.filter(user_id=user_id, key=ONE_CLICK_EMAIL_UNSUB_KEY).exists()
            preferences = CourseNotificationPreference.objects.create(
                user_id=user_id,
                course_id=course_id,
                is_active=True,
                notification_preference_config=NotificationAppManager().get_notification_app_preferences(email_opt_out)
            )
        current_config_version = get_course_notification_preference_config_version()
        if current_config_version != preferences.config_version:
            try:
                current_prefs = preferences.notification_preference_config
                new_prefs = NotificationPreferenceSyncManager.update_preferences(current_prefs, email_opt_out)
                preferences.config_version = current_config_version
                preferences.notification_preference_config = new_prefs
                preferences.save()
            # pylint: disable-next=broad-except
            except Exception as e:
                log.error(f'Unable to update notification preference to new config. {e}')
        return preferences

    @staticmethod
    def get_user_notification_preferences(user):
        """
        Checks if all user preferences have updated versions and returns the user preferences.
        Updates any preferences that need to be updated to the latest config version.
        """
        preferences = CourseNotificationPreference.objects.filter(user=user, is_active=True)
        email_opt_out = UserPreference.objects.filter(user_id=user.id, key=ONE_CLICK_EMAIL_UNSUB_KEY).exists()
        current_config_version = get_course_notification_preference_config_version()
        preferences_to_update = []

        try:
            for preference in preferences:
                if preference.config_version != current_config_version:
                    current_prefs = preference.notification_preference_config
                    new_prefs = NotificationPreferenceSyncManager.update_preferences(current_prefs, email_opt_out)
                    preference.config_version = current_config_version
                    preference.notification_preference_config = new_prefs
                    preferences_to_update.append(preference)
            if preferences_to_update:
                CourseNotificationPreference.objects.bulk_update(
                    preferences_to_update,
                    ['config_version', 'notification_preference_config']
                )
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.error(f'Unable to update notification preference to new config: {str(e)}')

        return preferences

    @staticmethod
    def get_updated_user_course_preferences(user, course_id):
        return CourseNotificationPreference.get_user_course_preference(user.id, course_id)

    def get_app_config(self, app_name) -> Dict:
        """
        Returns the app config for the given app name.
        """
        return self.notification_preference_config.get(app_name, {})

    def get_notification_types(self, app_name) -> Dict:
        """
        Returns the notification types for the given app name.

        Sample Response:
        {
            'new_comment_on_post': {
                'email': True,
                'push': True,
                'web': True,
                'info': 'Comment on post'
            },
            'new_response_on_comment': {
                'email': True,
                'push': True,
                'web': True,
                'info': 'Response on comment'
            },
        """
        return self.get_app_config(app_name).get('notification_types', {})

    def get_notification_type_config(self, app_name, notification_type) -> Dict:
        """
        Returns the notification type config for the given app name and notification type.

        Sample Response:
        {
            'email': True,
            'push': True,
            'web': True,
            'info': 'Comment on post'
        }
        """
        return self.get_notification_types(app_name).get(notification_type, {})

    def get_web_config(self, app_name, notification_type) -> bool:
        """
        Returns the web config for the given app name and notification type.
        """
        if self.is_core(app_name, notification_type):
            return self.get_core_config(app_name).get('web', False)
        return self.get_notification_type_config(app_name, notification_type).get('web', False)

    def is_enabled_for_any_channel(self, app_name, notification_type) -> bool:
        """
        Returns True if the notification type is enabled for any channel.
        """
        if self.is_core(app_name, notification_type):
            return any(self.get_core_config(app_name).get(channel, False) for channel in NOTIFICATION_CHANNELS)
        return any(self.get_notification_type_config(app_name, notification_type).get(channel, False) for channel in
                   NOTIFICATION_CHANNELS)

    def get_channels_for_notification_type(self, app_name, notification_type) -> list:
        """
        Returns the channels for the given app name and notification type.
        if notification is core then return according to core settings
        Sample Response:
        ['web', 'push']
        """
        if self.is_core(app_name, notification_type):
            notification_channels = [channel for channel in NOTIFICATION_CHANNELS if
                                     self.get_core_config(app_name).get(channel, False)]
            additional_channel_settings = [channel for channel in ADDITIONAL_NOTIFICATION_CHANNEL_SETTINGS if
                                           self.get_core_config(app_name).get(channel, False)]
        else:
            notification_channels = [channel for channel in NOTIFICATION_CHANNELS if
                                     self.get_notification_type_config(app_name, notification_type).get(channel, False)]
            additional_channel_settings = [channel for channel in ADDITIONAL_NOTIFICATION_CHANNEL_SETTINGS if
                                           self.get_notification_type_config(app_name, notification_type).get(channel,
                                                                                                              False)]

        return notification_channels + additional_channel_settings

    def is_core(self, app_name, notification_type) -> bool:
        """
        Returns True if the given notification type is a core notification type.
        """
        return notification_type in self.get_app_config(app_name).get('core_notification_types', [])

    def get_core_config(self, app_name) -> Dict:
        """
        Returns the core config for the given app name.

        Sample Response:
        {
            'email': True,
            'push': True,
            'web': True,
            'info': 'comment on post and response on comment'
        }
        """
        return self.get_notification_types(app_name).get('core', {})

    def is_email_enabled_for_notification_type(self, app_name, notification_type) -> bool:
        """
        Returns True if the email is enabled for the given app name and notification type.
        """
        if self.is_core(app_name, notification_type):
            return self.get_core_config(app_name).get('email', False)
        return self.get_notification_type_config(app_name, notification_type).get('email', False)

    def get_email_cadence_for_notification_type(self, app_name, notification_type) -> str:
        """
        Returns the email cadence for the given app name and notification type.
        """
        if self.is_core(app_name, notification_type):
            return self.get_core_config(app_name).get('email_cadence', EmailCadence.NEVER)
        return self.get_notification_type_config(app_name, notification_type).get('email_cadence', EmailCadence.NEVER)
