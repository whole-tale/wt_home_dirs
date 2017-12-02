from girder.utility.model_importer import ModelImporter
from girder.models.model_base import AccessException
import datetime

class WTDomainController(object):
    def __init__(self):
        self.userModel = ModelImporter.model('user')
        self.passwordModel = ModelImporter.model('password', 'wt_home_dir')
        self.tokenModel = ModelImporter.model('token')
        self.tokenCache = {}
        self.userCache = {}

    def __repr__(self):
        return self.__class__.__name__

    def getDomainRealm(self, inputURL, environ):
        return 'homes'

    def requireAuthentication(self, realmname, environ):
        return True

    def isRealmUser(self, realmname, username, environ):
        user = self._getUser(username)
        return user is not None

    def getRealmUserPassword(self, realmname, username, environ):
        raise Exception('Digest authentication is disabled')

    def authDomainUser(self, realmname, username, password, environ):
        if password.startswith('token:'):
            return self._authenticateToken(username, password)
        else:
            try:
                self.passwordModel.authenticate(username, password)
                return True
            except AccessException:
                return False

    def _authenticateToken(self, username, password):
        token = self._getToken(password[6:])
        if token is None:
            return False
        if not 'userId' in token:
            return False
        user = self._getUser(username)
        if token['userId'] != user['_id']:
            return False
        return True

    def _getUser(self, username):
        if username in self.userCache:
            return self.userCache[username]
        user = self.userModel.findOne({'login': username})
        if user is None:
            return None
        else:
            self.userCache[username] = user
            return user

    def _getToken(self, tokenStr):
        now = datetime.datetime.utcnow()
        if tokenStr in self.tokenCache:
            token = self.tokenCache[tokenStr]
        else:
            token = self.tokenModel.load(tokenStr, force=True, objectId=False)
            if token is None:
                return None
            else:
                self.tokenCache[tokenStr] = token
        if now > token['expires']:
            try:
                del self.tokenCache[tokenStr]
            except:
                pass
            return None
        return token