# 小鲸鱼像素立绘 v9  咿呀
import math
import os

W, H, S = 46, 64, 8
grid = [[None] * W for _ in range(H)]

C = dict(
    OUT="#12253F", HAIR_D="#27509A", HAIR_M="#4A88DB", HAIR_L="#8FC3F3",
    SPOT="#EAF4FF", SKIN="#FCEADC", SKIN_S="#E8C6AE", BLUSH="#FF9DB1",
    WHITE="#FFFFFF", DRESS_S="#DCE9FA", BELT="#4A86D8", GOLD="#FFC95C",
    SHELL="#F7E8CE", SHELL_D="#E3B07C", SHELL_D2="#B87C4A",
    WATER="#9FDBF8", WATER_L="#E7F7FF", MOUTH="#C9707A",
    TAIL="#5E9AE0", TAIL_L="#8FC2F2", TAIL_D="#2C5F9E",
)
for k, v in C.items():
    globals()[k] = v


def put(x, y, c):
    if 0 <= x < W and 0 <= y < H:
        grid[y][x] = c


def rect(x0, y0, x1, y1, c):
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            put(x, y, c)


def ell(cx, cy, rx, ry, c, y0=None, y1=None):
    for y in range(H):
        if y0 is not None and y < y0: continue
        if y1 is not None and y > y1: continue
        for x in range(W):
            if ((x + 0.5 - cx) / rx) ** 2 + ((y + 0.5 - cy) / ry) ** 2 <= 1.0:
                put(x, y, c)


def poly(pts, c):
    ys = [p[1] for p in pts]
    for y in range(int(math.floor(min(ys))), int(math.ceil(max(ys))) + 1):
        yc = y + 0.5
        xs = []
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]; x2, y2 = pts[(i + 1) % n]
            if (y1 <= yc < y2) or (y2 <= yc < y1):
                xs.append(x1 + (yc - y1) * (x2 - x1) / (y2 - y1))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            a, b = xs[i], xs[i + 1]
            for x in range(W):
                if a <= x + 0.5 <= b:
                    put(x, y, c)


# ===== 0. 鲸鱼尾鳍（身后右侧） =====
poly([(28, 52), (32, 46), (39, 46), (37, 50), (31, 53)], TAIL_D)   # 尾巴轮廓
ell(40.0, 42.0, 4.4, 3.2, TAIL_D)
ell(40.5, 50.0, 4.8, 3.2, TAIL_D)
poly([(28, 52), (32, 47), (38, 47), (36, 50), (31, 52)], TAIL)     # 尾柄
ell(39.6, 42.0, 3.6, 2.5, TAIL)                                    # 上叶
ell(40.2, 49.6, 4.0, 2.5, TAIL)                                    # 下叶
ell(38.6, 41.2, 1.8, 1.1, TAIL_L)                                  # 高光
put(41, 44, SPOT); put(40, 46, SPOT); put(38, 51, SPOT)

# ===== 1. 腿脚 =====
rect(17, 55, 20, 58, SKIN)
rect(25, 55, 28, 58, SKIN)
rect(26, 55, 26, 58, SKIN_S)
rect(16, 57, 21, 58, BELT)
rect(24, 57, 29, 58, BELT)
rect(17, 57, 20, 57, DRESS_S)
rect(25, 57, 28, 57, DRESS_S)

# ===== 2. 裙子 =====
poly([(16, 47), (30, 47), (35, 54), (11, 54)], WHITE)
rect(11, 53, 34, 54, DRESS_S)
poly([(16, 37), (30, 37), (30, 47), (16, 47)], WHITE)
ell(14.5, 39.0, 2.9, 3.2, WHITE)
ell(31.5, 39.0, 2.9, 3.2, WHITE)
rect(16, 48, 29, 49, BELT)
rect(22, 48, 23, 49, GOLD)

# ===== 3. 脖子 =====
rect(19, 33, 26, 36, SKIN)
rect(26, 33, 26, 36, SKIN_S)

# ===== 4. 手臂 + 手 =====
ell(14.5, 41, 2.9, 4.8, SKIN)
ell(31.5, 41, 2.9, 4.8, SKIN)
ell(14.0, 41, 1.0, 4.4, SKIN_S)
ell(32.0, 41, 1.0, 4.4, SKIN_S)
ell(18.5, 45.0, 3.1, 2.9, SKIN_S)
ell(27.5, 45.0, 3.1, 2.9, SKIN_S)
ell(18.5, 45.0, 2.4, 2.2, SKIN)
ell(27.5, 45.0, 2.4, 2.2, SKIN)
rect(16, 40, 16, 45, SKIN_S)
rect(29, 40, 29, 45, SKIN_S)

# ===== 5. 头顶喷水 =====
rect(21, 6, 24, 7, WATER)                       # 水柱
rect(20, 4, 25, 5, WATER)
rect(19, 3, 26, 3, WATER)
rect(21, 1, 24, 2, WATER_L)
put(18, 2, WATER_L); put(19, 2, WATER_L)
put(26, 2, WATER_L); put(27, 2, WATER_L)
rect(22, 4, 23, 7, WATER_L)                     # 水柱高光

# ===== 6. 头发 =====
ell(23, 20.5, 13.4, 12.2, HAIR_M)
rect(21, 8, 24, 8, OUT)
rect(21, 9, 24, 9, HAIR_D)
ell(12.5, 27, 3.8, 9.5, HAIR_M)
ell(33.5, 27, 3.8, 9.5, HAIR_M)
ell(12.5, 34, 2.6, 2.8, HAIR_M)
ell(33.5, 34, 2.6, 2.8, HAIR_M)

# ===== 7. 脸 =====
ell(23, 25.5, 8.8, 8.6, SKIN)

# ===== 8. 刘海 =====
ell(23, 14, 12.2, 7.2, HAIR_M, y0=9, y1=16)
for x0, x1, d in [(14, 17, 21), (18, 20, 20), (21, 24, 22),
                  (25, 27, 20), (28, 31, 21)]:
    rect(x0, 16, x1, d, HAIR_M)
# 头顶光泽（斜带）
put(19, 10, HAIR_L); put(20, 10, HAIR_L); put(21, 11, HAIR_L)
put(18, 11, HAIR_L); put(19, 11, HAIR_L); put(20, 12, HAIR_L)
put(18, 12, HAIR_L); put(17, 13, HAIR_L)

# ===== 9. 头发暗边 =====
for y in range(H):
    for x in range(W):
        if grid[y][x] == HAIR_M:
            l = grid[y][x - 1] if x > 0 else 'B'
            r = grid[y][x + 1] if x < W - 1 else 'B'
            if l is None or r is None:
                grid[y][x] = HAIR_D

# ===== 10. 白斑 =====
for p in [(11, 25), (11, 29), (14, 33), (34, 25), (34, 29), (31, 33)]:
    if grid[p[1]][p[0]] in (HAIR_M, HAIR_D):
        put(p[0], p[1], SPOT)

# ===== 11. 五官 =====
rect(17, 26, 20, 26, OUT)
put(16, 27, OUT); put(21, 27, OUT)
rect(25, 26, 28, 26, OUT)
put(24, 27, OUT); put(29, 27, OUT)
rect(15, 29, 16, 29, BLUSH)
rect(15, 30, 17, 30, BLUSH)
rect(29, 29, 30, 29, BLUSH)
rect(28, 30, 30, 30, BLUSH)
put(21, 31, MOUTH); put(24, 31, MOUTH)
put(22, 32, MOUTH); put(23, 32, MOUTH)

# ===== 12. 胸前的水泡 =====
ell(23, 43.5, 4.2, 3.3, OUT)
ell(23, 43.5, 3.5, 2.7, WATER)
ell(23, 43.0, 2.4, 1.7, WATER_L)
put(21, 42, SPOT)

# ===== 13. 外描边 =====
base = [row[:] for row in grid]
for y in range(H):
    for x in range(W):
        if base[y][x] is None and y >= 10:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < W and 0 <= ny < H and base[ny][nx] is not None:
                    grid[y][x] = OUT
                    break


def to_svg(bg=None):
    parts = []
    if bg:
        parts.append(f'<rect width="{W*S}" height="{H*S}" fill="{bg}"/>')
    for y in range(H):
        x = 0
        while x < W:
            c = grid[y][x]
            if c is None:
                x += 1
                continue
            x2 = x
            while x2 + 1 < W and grid[y][x2 + 1] == c:
                x2 += 1
            parts.append(f'<rect x="{x*S}" y="{y*S}" width="{(x2-x+1)*S}" height="{S}" fill="{c}"/>')
            x = x2 + 1
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W*S}" height="{H*S}" '
            f'viewBox="0 0 {W*S} {H*S}" shape-rendering="crispEdges">\n'
            + "\n".join(parts) + "\n</svg>\n")


MAP = {OUT: 'o', HAIR_D: 'd', HAIR_M: 'm', HAIR_L: 'l', SPOT: '*', SKIN: 's',
       SKIN_S: 'S', BLUSH: 'b', WHITE: 'w', DRESS_S: 'e', BELT: 't', GOLD: 'g',
       SHELL: 'h', SHELL_D: 'H', SHELL_D2: 'X', WATER: 'W', WATER_L: 'L',
       MOUTH: 'M', TAIL: 'T', TAIL_L: 'Y', TAIL_D: 'Z'}


def ascii_dump():
    out = []
    for y, row in enumerate(grid):
        out.append("%2d " % y + ''.join(MAP.get(c, '.') if c else '.' for c in row))
    out.append("   " + ''.join(str(x % 10) for x in range(W)))
    return "\n".join(out)


if __name__ == "__main__":
    d = os.path.expanduser('~/Desktop/')
    open(d + "f2.svg", "w").write(to_svg())
    print(ascii_dump())
