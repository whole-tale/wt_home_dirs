from girder.models.model_base import AccessControlledModel, AccessException
from girder.utility.model_importer import ModelImporter
from girder.constants import AccessType
from bson import objectid
import datetime
from passlib import pwd
from passlib.hash import pbkdf2_sha256 as pdigest


class Password(AccessControlledModel):
    NOT_LOCKED = datetime.datetime.min
    MAX_FAILURE_RATE = 5

    def initialize(self):
        self.name = 'password'
        self.exposeFields(level=AccessType.READ,
                          fields={'_id', 'userId', 'userName', 'hash', 'lockedUntil',
                                  'resetOn', 'failedCount'})
        self.itemModel = ModelImporter.model('item')

    def validate(self, password):
        return password

    def setPassword(self, user, password):
        existing = self.findOne({'userId': user['_id']})
        if existing is None:
            existing = {
                '_id': objectid.ObjectId(),
                'userId': user['_id'],
                'userName': user['login'],
                'lockedUntil': Password.NOT_LOCKED,
            }
        existing['hash'] = pdigest.hash(password)
        self.save(existing)
        return existing

    def generateAndSetPassword(self, user):
        password = self._generatePassword()
        self.setPassword(user, password)
        return {'password': password}

    def authenticate(self, username, password):
        entry = self.findOne({'userName': username})
        if entry is None:
            self._authenticationFailed()
            raise AccessException('Invalid username/password')
        self._checkLocked(entry)
        if not pdigest.verify(password, entry['hash']):
            self._authenticationFailed(entry)
            raise AccessException('Invalid username/password')

    def _checkLocked(self, entry):
        now = datetime.datetime.now()
        if 'resetOn' in entry and now > entry['resetOn']:
            del entry['resetOn']
            entry['failedCount'] = 0
            self.save(entry)
        if now < entry['lockedUntil']:
            raise AccessException('Too many authentication failures. Wait some time until trying '
                                  'again.')

    def _authenticationFailed(self, entry=None):
        if entry is None:
            # block IP?
            return
        now = datetime.datetime.now()
        if 'resetOn' not in entry or entry['resetOn'] is None:
            entry['resetOn'] = now + datetime.timedelta(minutes=1)
            entry['failedCount'] = 1
        failedCount = entry['failedCount']
        if failedCount > Password.MAX_FAILURE_RATE:
            entry['lockedUntil'] = now + datetime.timedelta(minutes=1)
        else:
            entry['failedCount'] = failedCount + 1
        self.save(entry)

    def _generatePassword(self):
        return pwd.genword()