#!/usr/bin/env python
# -*- coding: utf-8 -*-

from .constants import PluginSettings
from girder.models.setting import Setting
from girder.utility import setting_utilities
from girder.constants import SettingDefault
import os
import cherrypy
from wsgidav.wsgidav_app import DEFAULT_CONFIG, WsgiDAVApp
from wsgidav.dir_browser import WsgiDavDirBrowser
from wsgidav.debug_filter import WsgiDavDebugFilter
from wsgidav.http_authenticator import HTTPAuthenticator
from wsgidav.error_printer import ErrorPrinter
from .lib.Authorizer import Authorizer
from .lib.DirectoryInitializer import DirectoryInitializer
from .lib.WTDomainController import WTDomainController
from .lib.WTFilesystemProvider import WTFilesystemProvider
from .resources.homedirpass import Homedirpass


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

    provider = WTFilesystemProvider(homeDirsRoot)
    config = DEFAULT_CONFIG.copy()
    # Accept basic authentication and assume access through HTTPS only. This (HTTPS when only
    # basic is accepted) is enforced by some clients.
    # The reason for not accepting digest authentication is that it would require storage of
    # unsalted password hashes on the server. Maybe that's OK, since one could store
    # HA1 (md5(username:realm:password)) as specified by the digest auth RFC. But for now,
    # this seems simpler.
    config.update({
        'mount_path': '/homes',
        'wt_home_dirs_root': homeDirsRoot,
        'provider_mapping': {'/': provider},
        'user_mapping': {},
        'middleware_stack': [WsgiDavDirBrowser, DirectoryInitializer, Authorizer,
                             HTTPAuthenticator, ErrorPrinter, WsgiDavDebugFilter],
        'acceptbasic': True,
        'acceptdigest': False,
        'defaultdigest': False,
        'domaincontroller': WTDomainController(),
        'server': 'cherrypy'
    })
    cherrypy.tree.graft(WsgiDAVApp(config), '/homes')
    tree = cherrypy.tree
    print(tree)

    hdp = Homedirpass()
    info['apiRoot'].homedirpass = hdp
    info['apiRoot'].homedirpass.route('GET', ('generate',), hdp.generatePassword)
    info['apiRoot'].homedirpass.route('PUT', ('set',), hdp.setPassword)
