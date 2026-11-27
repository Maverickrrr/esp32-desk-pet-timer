import json
import os


def default(i):
    return dict(name=('通道一', '通道二')[i], start=480, minutes=1, enabled=False)


def validate(c):
    if not isinstance(c, dict):
        raise ValueError('配置格式错误')
    name = c.get('name')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 20:
        raise ValueError('名称需为 1–20 字')
    for key, low, high in [('start', 0, 1439), ('minutes', 1, 1439)]:
        if type(c.get(key)) != int or not low <= c[key] <= high:
            raise ValueError('时间超出范围')
    if type(c.get('enabled')) != bool:
        raise ValueError('开关格式错误')
    return dict(name=name.strip(), start=c['start'], minutes=c['minutes'], enabled=c['enabled'])


class Controller:
    def __init__(self, folder, output, platform):
        self.folder, self.output, self.platform = folder, output, platform
        self.seq = 0
        self.cfg = [default(0), default(1)]
        for slot in range(2):
            try:
                with open(self.path(slot)) as f:
                    seq, rows = json.load(f)
                if seq > self.seq and len(rows) == 2:
                    self.cfg = [validate(c) for c in rows]
                    self.seq = seq
            except (OSError, ValueError, TypeError, KeyError):
                pass
        self.ends = [0, 0]
        self.reason = ['', '']
        self.due = [None, None]
        self.events = []
        self.offset = None

    def path(self, slot):
        return self.folder + '/plan%d.json' % slot

    def wall(self, mono):
        return None if self.offset is None else mono + self.offset

    def schedule(self, i, now):
        c = self.cfg[i]
        self.due[i] = None
        if now is not None and c['enabled']:
            candidate = now // 86400 * 86400 + c['start'] * 60
            self.due[i] = candidate if candidate > now else candidate + 86400

    def log(self, i, action, mono):
        self.events.insert(0, [self.wall(mono), self.cfg[i]['name'], action])
        del self.events[16:]

    def run(self, i, reason, mono):
        self.output(i, True)
        self.ends[i] = mono + self.cfg[i]['minutes'] * 60
        self.reason[i] = reason
        self.log(i, reason, mono)

    def stop(self, i, mono):
        if self.reason[i]:
            self.output(i, False)
            self.reason[i] = ''
            self.ends[i] = 0
            self.log(i, '停止', mono)

    def tick(self, mono):
        now = self.wall(mono)
        for i in range(2):
            if self.reason[i] and mono >= self.ends[i]:
                self.stop(i, mono)
            due = self.due[i]
            if due is not None and now >= due:
                self.schedule(i, now)
                if now - due < 60 and not self.reason[i]:
                    self.run(i, '定时运行', mono)

    def dispatch(self, path, data, mono):
        self.tick(mono)
        if path == '/clock':
            wall = data.get('wall')
            if type(wall) != int or not 1600000000 <= wall <= 4102444800:
                raise ValueError('时间无效')
            if self.offset is None or abs(self.wall(mono) - wall) > 3:
                self.offset = wall - mono
                for i in range(2):
                    self.schedule(i, wall)
        elif path != '/status':
            i = data.get('id')
            if type(i) != int or i not in (0, 1):
                raise ValueError('通道无效')
            if path == '/config':
                rows = self.cfg[:]
                rows[i] = validate(data)
                seq = self.seq + 1
                with open(self.path(seq % 2), 'w') as f:
                    json.dump([seq, rows], f)
                self.cfg, self.seq = rows, seq
                self.schedule(i, self.wall(mono))
            elif path == '/run':
                if not self.reason[i]:
                    self.run(i, '手动运行', mono)
            elif path == '/stop':
                self.stop(i, mono)
            else:
                raise ValueError('未知操作')
        return dict(platform=self.platform, wall=self.wall(mono), cfg=self.cfg,
                    reason=self.reason, left=[max(0, x-mono) for x in self.ends],
                    due=self.due, events=self.events)
