# Non-consuming lookahead with zero history cache

A seekable iterator configured with maxlen=0 must allow peek() and bool() without consuming the next item seen by iteration. Repeated lookahead and interleaving with next() must preserve element order and values, including falsey values. elements() must remain empty in this mode. Preserve the existing empty-iterator/default and nonzero/default-cache behavior.
