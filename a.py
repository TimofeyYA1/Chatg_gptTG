n = int(input())
a = [list(map(int, input().split())) for _ in range(n)]

best = None
ans = (1, 2, 3)

for i in range(n):
    for j in range(i + 1, n):
        dij = a[i][j]
        for k in range(j + 1, n):
            s = dij + a[j][k] + a[k][i]
            if best is None or s < best:
                best = s
                ans = (i + 1, j + 1, k + 1)

print(*ans)
