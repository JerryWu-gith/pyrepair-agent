# Consistent addlist behavior for one-shot iterables

OrderedMultiDict/OMD and URL QueryParamDict addlist() must accept lists, iterators and generators consistently. Every input value must remain visible through getlist(), get(), keys(), items(multi=True), and length. Appending to an existing key must retain earlier values and insertion order; empty iterables must not create an empty key. QueryParamDict serialization must remain consistent with its stored query values.
