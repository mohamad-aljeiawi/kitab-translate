# The Cost of Abstraction

Every abstraction has a price. The question is never whether to pay it, but whether
you are getting something worth the money.

Consider a hash map. Lookup is $O(1)$ on average, which sounds free until you measure
it. See section 3.2.1 for the cache behaviour that makes `hash_lookup()` slower than a
linear scan over 16 elements.

## When to reach for one

- When the collection grows without bound
- When lookups outnumber insertions by a wide margin

> A data structure is a bet about how the data will be used.

| Structure | Lookup | Memory |
| --------- | ------ | ------ |
| Array     | O(n)   | Low    |
| Hash map  | O(1)   | High   |

```python
def hash_lookup(table, key):
    return table[hash(key) % len(table)]
```
