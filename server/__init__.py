#!/usr/bin/env python
# -*- coding: utf-8 -*-

from .constants import PluginSettings
from girder.models.setting import Setting
from girder.utility import setting_utilities
from girder.constants import SettingDefault
import os
import cherrypy
from wsgidav.fs_dav_provider import FilesystemProvider
from wsgidav.wsgidav_app import DEFAULT_CONFIG, WsgiDAVApp
from wsgidav.dir_browser import WsgiDavDirBrowser
from wsgidav.debug_filter import WsgiDavDebugFilter
from wsgidav.http_authenticator import HTTPAuthenticator
from wsgidav.error_printer import ErrorPrinter
from .lib.TokenValidator import TokenValidator
from .lib.Authorizer import Authorizer
from .lib.DirectoryInitializer import DirectoryInitializer


@setting_utilities.validator({
    PluginSettings.HOME_DIRS_ROOT,
})
def validateOtherSettings(event):
    pass


def load(info):
    SettingDefault.defaults[PluginSettings.HOME_DIRS_ROOT] = '/tmp/wt-home-dirs'

    settings = Setting()

    homeDirsRoot = settings.get(PluginSettings.HOME_DIRS_ROOT)

    if not os.path.exists(homeDirsRoot):
        os.makedirs(homeDirsRoot)

    provider = FilesystemProvider(homeDirsRoot)
    config = DEFAULT_CONFIG.copy()
    config.update({
        'mount_path': '/homes',
        'wt_home_dirs_root': homeDirsRoot,
        'provider_mapping': {'/': provider},
        'user_mapping': {},
        'middleware_stack': [WsgiDavDirBrowser, DirectoryInitializer, Authorizer,
                             HTTPAuthenticator, TokenValidator, ErrorPrinter, WsgiDavDebugFilter],
        'acceptbasic': False,
        'acceptdigest': True,
        'server': 'cherrypy',
        'trusted_auth_header': 'TOKEN_USER'
    })
    cherrypy.tree.graft(WsgiDAVApp(config), '/homes')
    tree = cherrypy.tree
    print(tree)