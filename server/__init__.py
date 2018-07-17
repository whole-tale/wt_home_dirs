#!/usr/bin/env python
# -*- coding: utf-8 -*-

import cherrypy
import os
import pathlib
import tempfile
from wsgidav.wsgidav_app import DEFAULT_CONFIG, WsgiDAVApp
from wsgidav.dir_browser import WsgiDavDirBrowser
from wsgidav.debug_filter import WsgiDavDebugFilter
from wsgidav.http_authenticator import HTTPAuthenticator
from wsgidav.error_printer import ErrorPrinter
from girder import logger
from girder import events
from girder.constants import ROOT_DIR
from girder.models.setting import Setting
from girder.utility import setting_utilities
from girder.constants import SettingDefault
from .constants import PluginSettings
from .lib.Authorizer import HomeAuthorizer, TaleAuthorizer
from .lib.DirectoryInitializer import HomeDirectoryInitializer, TaleDirectoryInitializer
from .lib.WTDomainController import WTDomainController
from .lib.WTFilesystemProvider import WTFilesystemProvider
from .lib.PathMapper import HomePathMapper, TalePathMapper
from .lib.WTAssetstoreTypes import WTAssetstoreTypes
from .lib.WTAssetstoreAdapter import WTHomeAssetstoreAdapter, WTTaleAssetstoreAdapter
from .lib.EventHandlers import Event, EventHandler, FolderSaveHandler, FolderDeleteHandler
from .lib.EventHandlers import ItemSaveHandler, AssetstoreQueryHandler, ItemCopyPrepareHandler
from .resources.homedirpass import Homedirpass
from girder.utility import assetstore_utilities


class AppEntry:
    def __init__(self, realm: str, pathMapper, app):
        self.realm = realm
        self.pathMapper = pathMapper
        self.app = app


class AppsList:
    def __init__(self):
        self.list = []
        self.map = {}

    def add(self, realm: str, pathMapper, app):
        self.addEntry(AppEntry(realm, pathMapper, app))

    def addEntry(self, appEntry: AppEntry):
        self.list.append(appEntry)
        self.map[appEntry.realm] = appEntry

    def entries(self):
        return self.list

    def getApp(self, realm: str):
        return self.map[realm]


HOME_DIRS_APPS = AppsList()


@setting_utilities.validator({
    PluginSettings.HOME_DIRS_ROOT,
    PluginSettings.TALE_DIRS_ROOT
})
def validateOtherSettings(event):
    pass


def pathRouter(h: EventHandler):
    def handler(event: Event):
        path = pathlib.Path(h.getPath(event))
        for e in HOME_DIRS_APPS.entries():
            if e.pathMapper.girderPathMatches(path):
                provider = e.app.providerMap['/']['provider']
                logger.debug('Handling %s (%s) using %s' % (event, path, provider.rootFolderPath))
                try:
                    h.run(event, path, e.pathMapper, provider)
                except Exception as ex:
                    # hey, girder, when you have stuff like this that can be asynchroneous you
                    # need a mechanism to propagate errors so that the exception doesn't end up
                    # ignored in your event dispatch thread
                    logger.warning('Exception caught while handling event %s: %s' % (event, ex))
                    raise
                return

    return handler


def startDAVServer(rootPath, directoryInitializer, authorizer, pathMapper, assetstoreType: int):
    if not os.path.exists(rootPath):
        os.makedirs(rootPath)

    provider = WTFilesystemProvider(rootPath, pathMapper, assetstoreType)
    realm = pathMapper.getRealm()
    config = DEFAULT_CONFIG.copy()
    # Accept basic authentication and assume access through HTTPS only. This (HTTPS when only
    # basic is accepted) is enforced by some clients.
    # The reason for not accepting digest authentication is that it would require storage of
    # unsalted password hashes on the server. Maybe that's OK, since one could store
    # HA1 (md5(username:realm:password)) as specified by the digest auth RFC, which would make
    # it harder to use pre-computed hashes. But for now, this seems simpler.
    config.update({
        'mount_path': '/' + realm,
        'wt_home_dirs_root': rootPath,
        'provider_mapping': {'/': provider},
        'user_mapping': {},
        'middleware_stack': [WsgiDavDirBrowser, directoryInitializer, authorizer,
                             HTTPAuthenticator, ErrorPrinter, WsgiDavDebugFilter],
        'acceptbasic': True,
        'acceptdigest': False,
        'defaultdigest': False,
        'domaincontroller': WTDomainController(realm),
        'server': 'cherrypy'
    })
    # Increase verbosity when running tests.
    if 'GIRDER_TEST_ASSETSTORE' in os.environ:
        config.update({'verbose': 2})
    global HOME_DIRS_APPS
    app = WsgiDAVApp(config)
    HOME_DIRS_APPS.add(realm, pathMapper, app)
    cherrypy.tree.graft(WsgiDAVApp(config), '/' + realm)


def setDefaults():
    for (name, key) in [('home', PluginSettings.HOME_DIRS_ROOT),
                        ('tale', PluginSettings.TALE_DIRS_ROOT)]:
        if 'GIRDER_TEST_ASSETSTORE' in os.environ:
            # roots for testing; they need to be initialized here because the tests
            # would have to load the plugin first which would mean that this method
            # would already have been called before being able to make calls to relevant
            # methods
            assetstorePath = os.path.join(ROOT_DIR, 'tests', 'assetstore')
            # make sure we start with a clean slate
            os.makedirs(assetstorePath, exist_ok=True)
            assetstorePath = tempfile.mkdtemp(prefix=name, dir=assetstorePath)
            SettingDefault.defaults[key] = assetstorePath
        else:
            # normal /tmp/wt-home-dirs, /tmp/wt-tale-dirs
            SettingDefault.defaults[key] = '/tmp/wt-%s-dirs' % name


def addAssetstores():
    assetstore_utilities.setAssetstoreAdapter(WTAssetstoreTypes.WT_HOME_ASSETSTORE,
                                              WTHomeAssetstoreAdapter)
    assetstore_utilities.setAssetstoreAdapter(WTAssetstoreTypes.WT_TALE_ASSETSTORE,
                                              WTTaleAssetstoreAdapter)


def load(info):
    events.bind('model.folder.remove', 'wt_home_dir', pathRouter(FolderDeleteHandler()))
    events.bind('model.upload.assetstore', 'wt_home_dir', pathRouter(AssetstoreQueryHandler()))
    events.bind('model.folder.save', 'wt_home_dir', pathRouter(FolderSaveHandler()))
    events.bind('model.item.save', 'wt_home_dir', pathRouter(ItemSaveHandler()))
    events.bind('model.item.copy.prepare', 'wt_home_dir', pathRouter(ItemCopyPrepareHandler()))

    setDefaults()
    addAssetstores()

    settings = Setting()

    homeDirsRoot = settings.get(PluginSettings.HOME_DIRS_ROOT)
    logger.info('WT Home Dirs root: %s' % homeDirsRoot)
    startDAVServer(homeDirsRoot, HomeDirectoryInitializer, HomeAuthorizer, HomePathMapper(),
                   WTAssetstoreTypes.WT_HOME_ASSETSTORE)

    taleDirsRoot = settings.get(PluginSettings.TALE_DIRS_ROOT)
    logger.info('WT Tale Dirs root: %s' % taleDirsRoot)
    startDAVServer(taleDirsRoot, TaleDirectoryInitializer, TaleAuthorizer, TalePathMapper(),
                   WTAssetstoreTypes.WT_TALE_ASSETSTORE)

    hdp = Homedirpass()
    info['apiRoot'].homedirpass = hdp
    info['apiRoot'].homedirpass.route('GET', ('generate',), hdp.generatePassword)
    info['apiRoot'].homedirpass.route('PUT', ('set',), hdp.setPassword)
