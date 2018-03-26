from girder.utility.model_importer import ModelImporter
from girder.models.model_base import AccessException
import datetime
import time


class CacheEntry:
    def __init__(self, value):
        self.value = value
        self.ts = time.time()

    def isExpired(self, delta):
        return time.time() - self.ts > delta


class Cache:
    def __init__(self, expirationTime=1.0):
        self.dict = {}
        self.expirationTime = expirationTime

    def get(self, key):
        try:
            entry = self.dict[key]
        except KeyError:
            return None
        if entry.isExpired(self.expirationTime):
            try:
                del self.dict[key]
            except KeyError:
                pass
            return None
        else:
            return entry.value

    def set(self, key, value):
        self.dict[key] = CacheEntry(value)

    def remove(self, key):
        try:
            del self.dict[key]
        except KeyError:
            pass

    def clear(self):
        self.dict.clear()


class WTDomainController(object):
    def __init__(self, realm):
        self.realm = realm
        self.userModel = ModelImporter.model('user')
        self.passwordModel = ModelImporter.model('password', 'wt_home_dir')
        self.tokenModel = ModelImporter.model('token')
        self.tokenCache = Cache()
        self.userCache = Cache()

    def __repr__(self):
        return self.__class__.__name__

    def clearCache(self):
        self.tokenCache.clear()
        self.userCache.clear()

    def getDomainRealm(self, inputURL, environ):
        return self.realm

    def requireAuthentication(self, realmname, environ):
        return True

    def isRealmUser(self, realmname, username, environ):
        user = self._getUser(username)
        return user is not None

    def getRealmUserPassword(self, realmname, username, environ):
        raise Exception('Digest authentication is disabled')

    def authDomainUser(self, realmname, username, password, environ):
        success = False
        if password.startswith('token:'):
            success = self._authenticateToken(username, password)
        else:
            try:
                self.passwordModel.authenticate(username, password)
                success = True
            except AccessException:
                success = False

        if success:
            environ['WT_DAV_USER_DICT'] = self._getUser(username)
        return success

    def _authenticateToken(self, username, password):
        token = self._getToken(password[6:])
        if token is None:
            return False
        if 'userId' not in token:
            return False
        user = self._getUser(username)
        if token['userId'] != user['_id']:
            return False
        return True

    def _getUser(self, username):
        user = self.userCache.get(username)
        if user is not None:
            return user
        user = self.userModel.findOne({'login': username})
        if user is None:
            return None
        else:
            self.userCache.set(username, user)
            return user

    def _getToken(self, tokenStr):
        now = datetime.datetime.utcnow()
        token = self.tokenCache.get(tokenStr)
        if token is None:
            token = self.tokenModel.load(tokenStr, force=True, objectId=False)
            if token is None:
                return None
            else:
                self.tokenCache.set(tokenStr, token)
        if now > token['expires']:
            try:
                self.tokenCache.remove[tokenStr]
            except KeyError:
                pass
            return None
        return token
