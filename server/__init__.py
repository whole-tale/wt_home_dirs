#!/usr/bin/env python
# -*- coding: utf-8 -*-

import cherrypy
import os
import pathlib
import shutil
import tempfile
from wsgidav.wsgidav_app import DEFAULT_CONFIG, WsgiDAVApp
from wsgidav.dir_browser import WsgiDavDirBrowser
from wsgidav.debug_filter import WsgiDavDebugFilter
from wsgidav.http_authenticator import HTTPAuthenticator
from wsgidav.error_printer import ErrorPrinter
from girder import logger
from girder import events
from girder.constants import ROOT_DIR, AccessType, CoreEventHandler
from girder.models.folder import Folder
from girder.models.setting import Setting
from girder.models.user import User
from girder.utility import setting_utilities
from girder.constants import SettingDefault
from girder.plugins.wholetale.models.tale import Tale

from .constants import PluginSettings, WORKSPACE_NAME
from .lib.Authorizer import HomeAuthorizer, TaleAuthorizer
from .lib.DirectoryInitializer import HomeDirectoryInitializer, TaleDirectoryInitializer
from .lib.WTDomainController import WTDomainController
from .lib.WTFilesystemProvider import WTFilesystemProvider
from .lib.PathMapper import HomePathMapper, TalePathMapper
from .resources.homedirpass import Homedirpass


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


class WTDAVApp(WsgiDAVApp):
    def __call__(self, environ, start_response):
        if 'HTTP_X_FORWARDED_PROTO' in environ:
            environ['wsgi.url_scheme'] = environ['HTTP_X_FORWARDED_PROTO']
        return super().__call__(environ, start_response)


def startDAVServer(rootPath, directoryInitializer, authorizer, pathMapper):
    if not os.path.exists(rootPath):
        os.makedirs(rootPath)

    provider = WTFilesystemProvider(rootPath, pathMapper)
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
    app = WTDAVApp(config)
    HOME_DIRS_APPS.add(realm, pathMapper, app)
    cherrypy.tree.graft(app, '/' + realm)


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


def setHomeFolderMapping(event: events.Event):
    user = event.info
    homeDirsRoot = Setting().get(PluginSettings.HOME_DIRS_ROOT)
    homeFolder = Folder().createFolder(
        user, "Home", parentType="user", public=False, creator=user
    )
    Folder().setUserAccess(homeFolder, user, AccessType.ADMIN, save=False)

    absDir = "%s/%s" % (homeDirsRoot, HomePathMapper().davToPhysical("/" + user["login"]))
    absDir = pathlib.Path(absDir)
    absDir.mkdir(parents=True, exist_ok=True)
    homeFolder.update({"fsPath": absDir.as_posix(), "isMapping": True})
    # We don't want to trigger events here, amirite?
    Folder().save(homeFolder, validate=True, triggerEvents=False)


def setTaleFolderMapping(event: events.Event):
    tale = event.info
    root_path = Setting().get(PluginSettings.TALE_DIRS_ROOT)
    creator = User().load(tale["creatorId"], force=True)
    workspace = Tale()._createAuxFolder(tale, WORKSPACE_NAME, creator=creator)
    absDir = "%s/%s" % (root_path, TalePathMapper().davToPhysical("/" + str(tale["_id"])))
    absDir = pathlib.Path(absDir)
    absDir.mkdir(parents=True, exist_ok=True)
    workspace.update({'fsPath': absDir.as_posix(), 'isMapping': True})
    Folder().save(workspace, validate=True, triggerEvents=False)
    tale["workspaceId"] = workspace["_id"]
    tale = Tale().save(tale)
    event.addResponse(tale)


def deleteWorkspace(event: events.Event):
    tale = event.info
    if (workspace := Folder().load(tale["workspaceId"], force=True)):
        if "fsPath" in workspace:
            shutil.rmtree(workspace["fsPath"])
        Folder().remove(workspace)


def load(info):
    setDefaults()

    settings = Setting()

    homeDirsRoot = settings.get(PluginSettings.HOME_DIRS_ROOT)
    logger.info('WT Home Dirs root: %s' % homeDirsRoot)
    startDAVServer(homeDirsRoot, HomeDirectoryInitializer, HomeAuthorizer, HomePathMapper())

    taleDirsRoot = settings.get(PluginSettings.TALE_DIRS_ROOT)
    logger.info('WT Tale Dirs root: %s' % taleDirsRoot)
    startDAVServer(taleDirsRoot, TaleDirectoryInitializer, TaleAuthorizer, TalePathMapper())

    events.unbind('model.user.save.created', CoreEventHandler.USER_DEFAULT_FOLDERS)
    events.bind('model.user.save.created', 'wt_home_dirs', setHomeFolderMapping)
    events.bind('model.tale.save.created', 'wt_home_dirs', setTaleFolderMapping)
    events.bind('model.tale.remove', 'wt_home_dirs', deleteWorkspace)

    hdp = Homedirpass()
    info['apiRoot'].homedirpass = hdp
    info['apiRoot'].homedirpass.route('GET', ('generate',), hdp.generatePassword)
    info['apiRoot'].homedirpass.route('PUT', ('set',), hdp.setPassword)

    Tale().exposeFields(level=AccessType.READ, fields={"workspaceId"})
