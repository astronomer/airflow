from werkzeug.security import check_password_hash
from typing import Dict, List, Set, Tuple

from flask_appbuilder.const import (
    LOGMSG_ERR_SEC_ADD_REGISTER_USER,
    LOGMSG_ERR_SEC_AUTH_LDAP,
    LOGMSG_ERR_SEC_AUTH_LDAP_TLS,
    LOGMSG_WAR_SEC_LOGIN_FAILED,
    LOGMSG_WAR_SEC_NOLDAP_OBJ,
)

import logging
log = logging.getLogger(__name__)


class AuthBackendDB:

    def __init__(self, security_manager):
        self.security_manager = security_manager

    def auth_user_db(self, username, password):
        """
        Method for authenticating user, auth db style

        :param username:
            The username or registered email address
        :param password:
            The password, will be tested against hashed password on db
        """
        if username is None or username == "":
            return None
        user = self.security_manager.find_user(username=username)
        if user is None:
            user = self.security_manager.find_user(email=username)
        if user is None or (not user.is_active):
            # Balance failure and success
            check_password_hash(
                "pbkdf2:sha256:150000$Z3t6fmj2$22da622d94a1f8118"
                "c0976a03d2f18f680bfff877c9a965db9eedc51bc0be87c",
                "password",
            )
            log.info(LOGMSG_WAR_SEC_LOGIN_FAILED.format(username))
            return None
        elif check_password_hash(user.password, password):
            self.security_manager.update_user_auth_stat(user, True)
            return user
        else:
            self.security_manager.update_user_auth_stat(user, False)
            log.info(LOGMSG_WAR_SEC_LOGIN_FAILED.format(username))
            return None


class AuthBackendLDAP:

    def __init__(self, app, security_manager):
        self.app = app
        self.security_manager = security_manager

        if "AUTH_LDAP_SERVER" not in app.config:
            raise Exception(
                "No AUTH_LDAP_SERVER defined on config" " with AUTH_LDAP authentication type."
            )
        app.config.setdefault("AUTH_LDAP_SEARCH", "")
        app.config.setdefault("AUTH_LDAP_SEARCH_FILTER", "")
        app.config.setdefault("AUTH_LDAP_APPEND_DOMAIN", "")
        app.config.setdefault("AUTH_LDAP_USERNAME_FORMAT", "")
        app.config.setdefault("AUTH_LDAP_BIND_USER", "")
        app.config.setdefault("AUTH_LDAP_BIND_PASSWORD", "")
        # TLS options
        app.config.setdefault("AUTH_LDAP_USE_TLS", False)
        app.config.setdefault("AUTH_LDAP_ALLOW_SELF_SIGNED", False)
        app.config.setdefault("AUTH_LDAP_TLS_DEMAND", False)
        app.config.setdefault("AUTH_LDAP_TLS_CACERTDIR", "")
        app.config.setdefault("AUTH_LDAP_TLS_CACERTFILE", "")
        app.config.setdefault("AUTH_LDAP_TLS_CERTFILE", "")
        app.config.setdefault("AUTH_LDAP_TLS_KEYFILE", "")
        # Mapping options
        app.config.setdefault("AUTH_LDAP_UID_FIELD", "uid")
        app.config.setdefault("AUTH_LDAP_GROUP_FIELD", "memberOf")
        app.config.setdefault("AUTH_LDAP_FIRSTNAME_FIELD", "givenName")
        app.config.setdefault("AUTH_LDAP_LASTNAME_FIELD", "sn")
        app.config.setdefault("AUTH_LDAP_EMAIL_FIELD", "mail")

    @property
    def auth_ldap_server(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_SERVER"]

    @property
    def auth_ldap_use_tls(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_USE_TLS"]

    @property
    def auth_ldap_search(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_SEARCH"]

    @property
    def auth_ldap_search_filter(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_SEARCH_FILTER"]

    @property
    def auth_ldap_bind_user(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_BIND_USER"]

    @property
    def auth_ldap_bind_password(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_BIND_PASSWORD"]

    @property
    def auth_ldap_append_domain(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_APPEND_DOMAIN"]

    @property
    def auth_ldap_username_format(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_USERNAME_FORMAT"]

    @property
    def auth_ldap_uid_field(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_UID_FIELD"]

    @property
    def auth_ldap_group_field(self) -> str:
        return self.appbuilder.get_app.config["AUTH_LDAP_GROUP_FIELD"]

    @property
    def auth_ldap_firstname_field(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_FIRSTNAME_FIELD"]

    @property
    def auth_ldap_lastname_field(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_LASTNAME_FIELD"]

    @property
    def auth_ldap_email_field(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_EMAIL_FIELD"]

    @property
    def auth_ldap_bind_first(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_BIND_FIRST"]

    @property
    def auth_ldap_allow_self_signed(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_ALLOW_SELF_SIGNED"]

    @property
    def auth_ldap_tls_demand(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_TLS_DEMAND"]

    @property
    def auth_ldap_tls_cacertdir(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_TLS_CACERTDIR"]

    @property
    def auth_ldap_tls_cacertfile(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_TLS_CACERTFILE"]

    @property
    def auth_ldap_tls_certfile(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_TLS_CERTFILE"]

    @property
    def auth_ldap_tls_keyfile(self):
        return self.appbuilder.get_app.config["AUTH_LDAP_TLS_KEYFILE"]

    def _search_ldap(self, ldap, con, username):
        """
        Searches LDAP for user.

        :param ldap: The ldap module reference
        :param con: The ldap connection
        :param username: username to match with AUTH_LDAP_UID_FIELD
        :return: ldap object array
        """
        # always check AUTH_LDAP_SEARCH is set before calling this method
        assert self.security_manager.auth_ldap_search, "AUTH_LDAP_SEARCH must be set"

        # build the filter string for the LDAP search
        if self.security_manager.auth_ldap_search_filter:
            filter_str = "(&{}({}={}))".format(
                self.security_manager.auth_ldap_search_filter, self.security_manager.auth_ldap_uid_field, username
            )
        else:
            filter_str = f"({self.security_manager.auth_ldap_uid_field}={username})"

        # build what fields to request in the LDAP search
        request_fields = [
            self.security_manager.auth_ldap_firstname_field,
            self.security_manager.auth_ldap_lastname_field,
            self.security_manager.auth_ldap_email_field,
        ]
        if len(self.security_manager.auth_roles_mapping) > 0:
            request_fields.append(self.security_manager.auth_ldap_group_field)

        # preform the LDAP search
        log.debug(
            "LDAP search for '{}' with fields {} in scope '{}'".format(
                filter_str, request_fields, self.security_manager.auth_ldap_search
            )
        )
        raw_search_result = con.search_s(
            self.security_manager.auth_ldap_search, ldap.SCOPE_SUBTREE, filter_str, request_fields
        )
        log.debug(f"LDAP search returned: {raw_search_result}")

        # Remove any search referrals from results
        search_result = [
            (dn, attrs) for dn, attrs in raw_search_result if dn is not None and isinstance(attrs, dict)
        ]

        # only continue if 0 or 1 results were returned
        if len(search_result) > 1:
            log.error(
                "LDAP search for '{}' in scope '{}' returned multiple results".format(
                    filter_str, self.security_manager.auth_ldap_search
                )
            )
            return None, None

        try:
            # extract the DN
            user_dn = search_result[0][0]
            # extract the other attributes
            user_info = search_result[0][1]
            # return
            return user_dn, user_info
        except (IndexError, NameError):
            return None, None

    def _ldap_calculate_user_roles(self, user_attributes: Dict[str, bytes]) -> List[str]:
        user_role_objects = set()

        # apply AUTH_ROLES_MAPPING
        if len(self.security_manager.auth_roles_mapping) > 0:
            user_role_keys = self.security_manager.ldap_extract_list(user_attributes, self.security_manager.auth_ldap_group_field)
            user_role_objects.update(self.security_manager.get_roles_from_keys(user_role_keys))

        # apply AUTH_USER_REGISTRATION
        if self.security_manager.auth_user_registration:
            registration_role_name = self.security_manager.auth_user_registration_role

            # lookup registration role in flask db
            fab_role = self.security_manager.find_role(registration_role_name)
            if fab_role:
                user_role_objects.add(fab_role)
            else:
                log.warning(f"Can't find AUTH_USER_REGISTRATION role: {registration_role_name}")

        return list(user_role_objects)

    def _ldap_bind_indirect(self, ldap, con) -> None:
        """
        Attempt to bind to LDAP using the AUTH_LDAP_BIND_USER.

        :param ldap: The ldap module reference
        :param con: The ldap connection
        """
        # always check AUTH_LDAP_BIND_USER is set before calling this method
        assert self.security_manager.auth_ldap_bind_user, "AUTH_LDAP_BIND_USER must be set"

        try:
            log.debug(f"LDAP bind indirect TRY with username: '{self.security_manager.auth_ldap_bind_user}'")
            con.simple_bind_s(self.security_manager.auth_ldap_bind_user, self.security_manager.auth_ldap_bind_password)
            log.debug(f"LDAP bind indirect SUCCESS with username: '{self.security_manager.auth_ldap_bind_user}'")
        except ldap.INVALID_CREDENTIALS as ex:
            log.error(
                "AUTH_LDAP_BIND_USER and AUTH_LDAP_BIND_PASSWORD are" " not valid LDAP bind credentials"
            )
            raise ex

    @staticmethod
    def _ldap_bind(ldap, con, dn: str, password: str) -> bool:
        """
        Validates/binds the provided dn/password with the LDAP sever.
        """
        try:
            log.debug(f"LDAP bind TRY with username: '{dn}'")
            con.simple_bind_s(dn, password)
            log.debug(f"LDAP bind SUCCESS with username: '{dn}'")
            return True
        except ldap.INVALID_CREDENTIALS:
            return False

    @staticmethod
    def ldap_extract(ldap_dict: Dict[str, bytes], field_name: str, fallback: str) -> str:
        raw_value = ldap_dict.get(field_name, [bytes()])
        # decode - if empty string, default to fallback, otherwise take first element
        return raw_value[0].decode("utf-8") or fallback

    @staticmethod
    def ldap_extract_list(ldap_dict: Dict[str, bytes], field_name: str) -> List[str]:
        raw_list = ldap_dict.get(field_name, [])
        # decode - removing empty strings
        return [x.decode("utf-8") for x in raw_list if x.decode("utf-8")]

    def auth_user_ldap(self, username, password):
        """
        Method for authenticating user with LDAP.

        NOTE: this depends on python-ldap module

        :param username: the username
        :param password: the password
        """
        # If no username is provided, go away
        if (username is None) or username == "":
            return None

        # Search the DB for this user
        user = self.security_manager.find_user(username=username)

        # If user is not active, go away
        if user and (not user.is_active):
            return None

        # If user is not registered, and not self-registration, go away
        if (not user) and (not self.security_manager.auth_user_registration):
            return None

        # Ensure python-ldap is installed
        try:
            import ldap
        except ImportError:
            log.error("python-ldap library is not installed")
            return None

        try:
            # LDAP certificate settings
            if self.security_manager.auth_ldap_allow_self_signed:
                ldap.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_ALLOW)
                ldap.set_option(ldap.OPT_X_TLS_NEWCTX, 0)
            elif self.security_manager.auth_ldap_tls_demand:
                ldap.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_DEMAND)
                ldap.set_option(ldap.OPT_X_TLS_NEWCTX, 0)
            if self.security_manager.auth_ldap_tls_cacertdir:
                ldap.set_option(ldap.OPT_X_TLS_CACERTDIR, self.security_manager.auth_ldap_tls_cacertdir)
            if self.security_manager.auth_ldap_tls_cacertfile:
                ldap.set_option(ldap.OPT_X_TLS_CACERTFILE, self.security_manager.auth_ldap_tls_cacertfile)
            if self.security_manager.auth_ldap_tls_certfile:
                ldap.set_option(ldap.OPT_X_TLS_CERTFILE, self.security_manager.auth_ldap_tls_certfile)
            if self.security_manager.auth_ldap_tls_keyfile:
                ldap.set_option(ldap.OPT_X_TLS_KEYFILE, self.security_manager.auth_ldap_tls_keyfile)

            # Initialise LDAP connection
            con = ldap.initialize(self.security_manager.auth_ldap_server)
            con.set_option(ldap.OPT_REFERRALS, 0)
            if self.security_manager.auth_ldap_use_tls:
                try:
                    con.start_tls_s()
                except Exception:
                    log.error(LOGMSG_ERR_SEC_AUTH_LDAP_TLS.format(self.security_manager.auth_ldap_server))
                    return None

            # Define variables, so we can check if they are set in later steps
            user_dn = None
            user_attributes = {}

            # Flow 1 - (Indirect Search Bind):
            #  - in this flow, special bind credentials are used to preform the
            #    LDAP search
            #  - in this flow, AUTH_LDAP_SEARCH must be set
            if self.security_manager.auth_ldap_bind_user:
                # Bind with AUTH_LDAP_BIND_USER/AUTH_LDAP_BIND_PASSWORD
                # (authorizes for LDAP search)
                self.security_manager._ldap_bind_indirect(ldap, con)

                # Search for `username`
                #  - returns the `user_dn` needed for binding to validate credentials
                #  - returns the `user_attributes` needed for
                #    AUTH_USER_REGISTRATION/AUTH_ROLES_SYNC_AT_LOGIN
                if self.security_manager.auth_ldap_search:
                    user_dn, user_attributes = self.security_manager._search_ldap(ldap, con, username)
                else:
                    log.error("AUTH_LDAP_SEARCH must be set when using AUTH_LDAP_BIND_USER")
                    return None

                # If search failed, go away
                if user_dn is None:
                    log.info(LOGMSG_WAR_SEC_NOLDAP_OBJ.format(username))
                    return None

                # Bind with user_dn/password (validates credentials)
                if not self.security_manager._ldap_bind(ldap, con, user_dn, password):
                    if user:
                        self.security_manager.update_user_auth_stat(user, False)

                    # Invalid credentials, go away
                    log.info(LOGMSG_WAR_SEC_LOGIN_FAILED.format(username))
                    return None

            # Flow 2 - (Direct Search Bind):
            #  - in this flow, the credentials provided by the end-user are used
            #    to preform the LDAP search
            #  - in this flow, we only search LDAP if AUTH_LDAP_SEARCH is set
            #     - features like AUTH_USER_REGISTRATION & AUTH_ROLES_SYNC_AT_LOGIN
            #       will only work if AUTH_LDAP_SEARCH is set
            else:
                # Copy the provided username (so we can apply formatters)
                bind_username = username

                # update `bind_username` by applying AUTH_LDAP_APPEND_DOMAIN
                #  - for Microsoft AD, which allows binding with userPrincipalName
                if self.security_manager.auth_ldap_append_domain:
                    bind_username = bind_username + "@" + self.security_manager.auth_ldap_append_domain

                # Update `bind_username` by applying AUTH_LDAP_USERNAME_FORMAT
                #  - for transforming the username into a DN,
                #    for example: "uid=%s,ou=example,o=test"
                if self.security_manager.auth_ldap_username_format:
                    bind_username = self.security_manager.auth_ldap_username_format % bind_username

                # Bind with bind_username/password
                # (validates credentials & authorizes for LDAP search)
                if not self.security_manager._ldap_bind(ldap, con, bind_username, password):
                    if user:
                        self.security_manager.update_user_auth_stat(user, False)

                    # Invalid credentials, go away
                    log.info(LOGMSG_WAR_SEC_LOGIN_FAILED.format(bind_username))
                    return None

                # Search for `username` (if AUTH_LDAP_SEARCH is set)
                #  - returns the `user_attributes`
                #    needed for AUTH_USER_REGISTRATION/AUTH_ROLES_SYNC_AT_LOGIN
                #  - we search on `username` not `bind_username`,
                #    because AUTH_LDAP_APPEND_DOMAIN and AUTH_LDAP_USERNAME_FORMAT
                #    would result in an invalid search filter
                if self.security_manager.auth_ldap_search:
                    user_dn, user_attributes = self.security_manager._search_ldap(ldap, con, username)

                    # If search failed, go away
                    if user_dn is None:
                        log.info(LOGMSG_WAR_SEC_NOLDAP_OBJ.format(username))
                        return None

            # Sync the user's roles
            if user and user_attributes and self.security_manager.auth_roles_sync_at_login:
                user.roles = self.security_manager._ldap_calculate_user_roles(user_attributes)
                log.debug(f"Calculated new roles for user='{user_dn}' as: {user.roles}")

            # If the user is new, register them
            if (not user) and user_attributes and self.security_manager.auth_user_registration:
                user = self.security_manager.add_user(
                    username=username,
                    first_name=self.security_manager.ldap_extract(user_attributes, self.security_manager.auth_ldap_firstname_field, ""),
                    last_name=self.security_manager.ldap_extract(user_attributes, self.security_manager.auth_ldap_lastname_field, ""),
                    email=self.security_manager.ldap_extract(
                        user_attributes,
                        self.security_manager.auth_ldap_email_field,
                        f"{username}@email.notfound",
                    ),
                    role=self.security_manager._ldap_calculate_user_roles(user_attributes),
                )
                log.debug(f"New user registered: {user}")

                # If user registration failed, go away
                if not user:
                    log.info(LOGMSG_ERR_SEC_ADD_REGISTER_USER.format(username))
                    return None

            # LOGIN SUCCESS (only if user is now registered)
            if user:
                self.security_manager.update_user_auth_stat(user)
                return user
            else:
                return None

        except ldap.LDAPError as e:
            msg = None
            if isinstance(e, dict):
                msg = getattr(e, "message", None)
            if (msg is not None) and ("desc" in msg):
                log.error(LOGMSG_ERR_SEC_AUTH_LDAP.format(e.message["desc"]))
                return None
            else:
                log.error(e)
                return None
