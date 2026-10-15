# multi_inventory

Warehouse.reserve(q) subtracts q when q is a positive integer no greater than stock, otherwise raises ValueError without changing stock. release(q) restores q. Reservations hold q units and initially are active. cancel releases exactly that quantity once; later cancel calls are no-ops.

Fix production code; preserve public APIs and visible tests.
