# Livebook 0.19.7's rebar3 deps (aws_credentials, and katana_code behind the
# rebar3_lint plugin) build with warnings_as_errors and trip OTP 29's
# deprecations of gen_server:format_status/2 and bare 'catch'. Suppress those two
# warning classes for this recipe's deps; mix.bbclass exports "deterministic"
# alone, and ERL_COMPILER_OPTIONS is merged with each dep's own rebar.config so
# warnings_as_errors stays in force for everything else.
export ERL_COMPILER_OPTIONS = "[deterministic, nowarn_deprecated_callback, nowarn_deprecated_catch]"
