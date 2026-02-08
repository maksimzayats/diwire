import timeit


class Data:
    def resolve(self):
        return "42"


class Data2:
    def __init__(self, data: Data):
        self.data = data
        self.resolve = data.resolve


class Data3:
    def __init__(self, data: Data):
        self.data = data

    def resolve(self):
        return self.data.resolve()


d = Data()
d2 = Data2(d)
d3 = Data3(d)


def bench_d2():
    return d2.resolve()

def bench_d3():
    return d3.resolve()


b1 = timeit.timeit(bench_d2, number=1_000_000)
b2 = timeit.timeit(bench_d3, number=1_000_000)

print(f"Data2: {b1}")
print(f"Data3: {b2}")