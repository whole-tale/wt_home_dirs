# WholeTale Home Dirs

This is a Girder plugin that adds user home directory capability accessible
through WebDAV. It uses [WsgiDAV](https://github.com/mar10/wsgidav).

### Access

The WebDAV URL is `/homes/<username>`. Example:

    fusedav https://localhost:8080/homes/wtuser ~/wthome

### Configuration

#### wt.homedir.root

Specifies where the home directory data is stored. This should be a filesystem
path accessible by the Girder server. If this path does not exist, it will be created. User home directories are stored in specific user directories and are named `<wt.homedir.root>/<username>`.

### Authentication

The plugin is configured to only accept basic authentication. It should only be
used over HTTPS. The other choice would have been digest authentication. The reason for avoiding that is that it either requires storing plaintext (or obfuscated) passwords or a hash (HA1 - see [Digest Access Authentication](https://en.wikipedia.org/wiki/Digest_access_authentication)) that could potentially be susceptible to dictionary attacks. So complexity + not such a good idea = use the other thing.

Authentication itself is done using either the OAUTH token, a user-specified password, or an automatically generated password. If the Girder OAUTH token is used, the password must be constructed by pre-pending `token:` to the token value. Example:

    fusedav -u wtuser \
    -p token:jPuIdOjh9A1Q1Bhshxop7yuhToKSM0WgdVZxGQqHjUTLEeHQ65qzVZ9faBW6WpEz \
    https://localhost:8080/homes/wtuser ~/wthome

Users can either set a password or request a random password using `/#homedir/password`. Only one password can be active at a time and generating a random password or setting a new password overwrited previous passwords. If user-set or generated passwords are used, they should be specified directly when authenticating:

    fusedav -u wtuser -p p7yuhToK \
    https://localhost:8080/homes/wtuser ~/wthome

There is some throttling enabled. More than 5 failed authentication requests for one user in one minute will trigger a lockout for the remainig time in that minute (or at least that's the intention of the code).

### API

At this point the API is limited to password management.

#### Set password

```
PUT /homedirpass/set
```

The user for which the WebDAV password is being set must be the current user. The password must be sent as form data in a string.

#### Generate password

```
GET /homedirpass/generate
```

There are no parameters. The generated password is returned as a JSON object in the form `{'password': <password>}`
