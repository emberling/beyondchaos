from copy import deepcopy, copy
from utils import (ANCIENT_CHECKPOINTS_TABLE, TOWER_CHECKPOINTS_TABLE,
                   TOWER_LOCATIONS_TABLE, TREASURE_ROOMS_TABLE,
                   ENTRANCE_REACHABILITY_TABLE,
                   utilrandom as random)
from locationrandomizer import (get_locations, get_location,
                                get_unused_locations, Entrance,
                                add_location_map)
from formationrandomizer import get_fsets, get_formations
from chestrandomizer import ChestBlock
from itertools import product
from sys import stdout

SIMPLE, OPTIONAL, DIRECTIONAL = 's', 'o', 'd'
MAX_NEW_EXITS = 1000
MAX_NEW_MAPS = None  # 23: 6 more for fanatics tower, 1 more for bonus
ANCIENT = True
PROTECTED = [0, 1, 2, 3, 0xB, 0xC, 0xD, 0x11,
             0x37, 0x81, 0x82, 0x88, 0x9c, 0xb6, 0xb8, 0xbd, 0xbe,
             0xd2, 0xd3, 0xd4, 0xd5, 0xd7, 0xfe, 0xff,
             0x100, 0x102, 0x103, 0x104, 0x105, 0x10c, 0x12e,
             0x131, 0x132,  # Tzen WoR?
             0x139, 0x13a, 0x13b, 0x13c,  # Phoenix Cave
             0x13d,  # Three Stooges
             0x143, 0x144,  # Albrook
             0x154, 0x155, 0x157, 0x158,  # Thamasa
             0xe7, 0xe9, 0xea,  # opera with dancers?
             0x150, 0x164, 0x165, 0x19a, 0x19e]
PROTECTED += range(359, 371)  # Fanatics Tower
PROTECTED += range(382, 389)  # Sealed Gate
FIXED_ENTRANCES, REMOVE_ENTRANCES = [], []

locdict = {}
old_entrances = {}
towerlocids = [int(line.strip(), 0x10) for line in open(TOWER_LOCATIONS_TABLE)]
map_bans = []
newfsets = {}
clusters = None


class Cluster:
    def __init__(self, locid, clusterid):
        self.locid = locid
        self.clusterid = clusterid
        self.entrances = []

    @property
    def singleton(self):
        return len(self.entrances) == 1

    def add_entrance(self, entrance):
        e = Entrance()
        e.copy(entrance)
        self.entrances.append(e)

    @property
    def entids(self):
        return [e.entid for e in self.entrances]

    @property
    def free_entrances(self):
        free = [e for e in self.entrances if (e.location.locid, e.entid) not in
                FIXED_ENTRANCES + REMOVE_ENTRANCES]
        return free

    def __repr__(self):
        display = "; ".join([str(e) for e in self.entrances])
        return display


class RestStop(Cluster):
    def __init__(self, rank):
        self.rank = rank
        e = Entrance()
        e.location = get_location(413)
        e.x, e.y = 48, 21
        e.dest, e.destx, e.desty = 0, 0, 0
        e.entid = None
        self.entrances = [e]

    def __repr__(self):
        return "Rest stop rank %s" % self.rank


def get_clusters():
    global clusters
    if clusters is not None:
        return clusters

    clusters = []
    for i, line in enumerate(open(ENTRANCE_REACHABILITY_TABLE)):
        locid, entids = line.strip().split(':')
        locid = int(locid)
        entids = map(int, entids.split(','))
        loc = get_location(locid)
        entrances = [e for e in loc.entrances if e.entid in entids]
        c = Cluster(locid=locid, clusterid=i)
        for e in entrances:
            c.add_entrance(e)
        c.original_entrances = list(c.entrances)
        clusters.append(c)

    return get_clusters()


def get_cluster(locid, entid):
    for c in get_clusters():
        if c.locid == locid and entid in c.entids:
            return c


class Segment:
    def __init__(self, checkpoints):
        self.clusters = []
        self.entids = []
        for locid, entid in checkpoints:
            if locid == "R":
                c = RestStop(rank=entid)
                self.clusters.append(c)
                self.entids.append(None)
            else:
                c = get_cluster(locid, entid)
                assert c is not None
                self.clusters.append(c)
                self.entids.append(entid)
            c.exiting, c.entering = False, False
        self.intersegments = [InterSegment() for c in self.clusters[:-1]]
        self.original_clusters = list(self.clusters)

    @property
    def consolidated_links(self):
        links = list(self.links)
        for inter in self.intersegments:
            links.extend(inter.links)
        return links

    def check_links(self):
        links = self.consolidated_links
        linked_entrances = []
        for a, b in links:
            linked_entrances.append(a)
            linked_entrances.append(b)
        assert len(linked_entrances) == len(set(linked_entrances))

    def interconnect(self):
        links = []
        for segment in self.intersegments:
            segment.interconnect()
        for i, (a, b) in enumerate(zip(self.clusters, self.clusters[1:])):
            aid = self.entids[i]
            bid = self.entids[i+1]
            if a.singleton:
                acands = a.entrances
            elif i == 0:
                acands = [e for e in a.entrances if e.entid == aid]
            else:
                acands = [e for e in a.entrances if e.entid != aid]
            aent = random.choice(acands)
            bcands = [e for e in b.entrances if e.entid == bid]
            bent = bcands[0]
            inter = self.intersegments[i]
            if a.singleton:
                excands = inter.get_external_candidates(num=2, test=True)
                if excands is None and i > 0:
                    previnter = self.intersegments[i-1]
                    excands = previnter.get_external_candidates(num=1)
                if excands is None or len(excands) == 2:
                    excands = inter.get_external_candidates(num=1)
                if excands is None:
                    raise Exception("Routing error.")
                links.append((aent, excands[0]))
                a.entering, a.exiting = True, True
            elif not inter.empty:
                if not b.singleton:
                    excands = inter.get_external_candidates(num=2)
                    random.shuffle(excands)
                    links.append((bent, excands[1]))
                else:
                    excands = inter.get_external_candidates(num=1)
                links.append((aent, excands[0]))
                a.exiting = True
                b.entering = True
            elif (inter.empty and not b.singleton):
                links.append((aent, bent))
                a.exiting = True
                b.entering = True
            elif (inter.empty and b.singleton):
                inter2 = self.intersegments[i+1]
                assert not inter2.empty
                excands = inter2.get_external_candidates(num=1)
                links.append((aent, excands[0]))
                a.exiting = True
            else:
                import pdb; pdb.set_trace()
                assert False

        for i, a in enumerate(self.clusters):
            aid = self.entids[i]
            if not (a.entering or i == 0):
                if a.singleton:
                    aent = a.entrances[0]
                else:
                    acands = [e for e in a.entrances if e.entid == aid]
                    aent = acands[0]
                while i > 0:
                    inter = self.intersegments[i-1]
                    if not inter.empty:
                        break
                    i += -1
                if inter.empty:
                    raise Exception("Routing error.")
                excands = inter.get_external_candidates(num=1)
                links.append((aent, excands[0]))
                a.entering = True

        self.links = links
        try:
            self.check_links()
        except:
            import pdb; pdb.set_trace()

    def add_cluster(self, cluster, need=False):
        self.entids.append(None)
        self.clusters.append(cluster)
        if need:
            self.need -= len(cluster.entrances) - 2

    @property
    def free_entrances(self):
        free = []
        for (entid, cluster) in zip(self.entids, self.clusters):
            if entid is not None:
                clustfree = cluster.free_entrances
                clustfree = [e for e in clustfree if e.entid != entid]
                free.extend(clustfree)
        return free

    @property
    def reserved_entrances(self):
        free = self.free_entrances
        reserved = []
        for cluster in self.clusters:
            if isinstance(cluster, Cluster):
                reserved.extend([e for e in cluster.entrances
                                 if e not in free])
        return reserved

    def determine_need(self):
        for segment in self.intersegments:
            segment.need = 0
        for index, cluster in enumerate(self.clusters):
            if len(cluster.entrances) == 1:
                indexes = [i for i in [index-1, index]
                           if 0 <= i < len(self.intersegments)]
                self.intersegments[random.choice(indexes)].need += 1

    def __repr__(self):
        display = ""
        for i, cluster in enumerate(self.clusters):
            entid = self.entids[i]
            if entid is None:
                entid = '?'
            display += "%s %s\n" % (entid, cluster)
            if not isinstance(self, InterSegment):
                if i < len(self.intersegments):
                    display += str(self.intersegments[i]) + "\n"
        display = display.strip()
        if not display:
            display = "."
        if not isinstance(self, InterSegment):
            display += "\nCONNECT %s" % self.consolidated_links
        return display


class InterSegment(Segment):
    def __init__(self):
        self.clusters = []
        self.entids = []
        self.links = []
        self.linked_edge = []

    @property
    def empty(self):
        return len(self.clusters) == 0

    @property
    def linked_entrances(self):
        linked = []
        for a, b in self.links:
            linked.append(a)
            linked.append(b)
        for e in self.linked_edge:
            linked.append(e)
        return linked

    def get_external_candidates(self, num=2, test=False):
        if not self.clusters:
            return None
        candidates = []
        linked_clusters = []
        for e in self.linked_entrances:
            for c in self.clusters:
                if e in c.entrances:
                    linked_clusters.append(c)
        done_clusts = set([])
        done_ents = set(self.linked_entrances)
        for _ in xrange(num):
            candclusts = [c for c in self.clusters if c not in done_clusts]
            if not candclusts:
                candclusts = self.clusters
            candclusts = [c for c in candclusts if set(c.entrances)-done_ents]
            if not candclusts:
                candclusts = [c for c in self.clusters if c not in done_clusts
                              and set(c.entrances)-done_ents]
                if not candclusts:
                    candclusts = [c for c in self.clusters
                                  if set(c.entrances)-done_ents]
            if candclusts and linked_clusters:
                lowclust = min(candclusts,
                               key=lambda c: linked_clusters.count(c))
                lowest = linked_clusters.count(lowclust)
                candclusts = [c for c in candclusts
                              if linked_clusters.count(c) == lowest]
                assert lowclust in candclusts
            try:
                chosen = random.choice(candclusts)
            except IndexError:
                return None
            done_clusts.add(chosen)
            chosen = random.choice([c for c in chosen.entrances
                                    if c not in done_ents])
            done_ents.add(chosen)
            candidates.append(chosen)
        if not test:
            self.linked_edge.extend(candidates)
        return candidates

    def interconnect(self):
        self.links = []
        if len(self.clusters) < 2:
            return

        starter = max(self.clusters, key=lambda c: len(c.entrances))
        while True:
            links = []
            done_ents = set([])
            done_clusts = set([starter])
            clusters = self.clusters
            random.shuffle(clusters)
            for c in clusters:
                if c in done_clusts:
                    continue
                candidates = [c2 for c2 in done_clusts
                              if set(c2.entrances) - done_ents]
                if not candidates:
                    break
                chosen = random.choice(candidates)
                acands = [e for e in c.entrances if e not in done_ents]
                bcands = [e for e in chosen.entrances if e not in done_ents]
                a, b = random.choice(acands), random.choice(bcands)
                done_clusts.add(c)
                done_ents.add(a)
                done_ents.add(b)
                links.append((a, b))
            if done_clusts == set(self.clusters):
                break
        self.links = links


class Route:
    def __init__(self, segments):
        self.segments = segments

    def determine_need(self):
        for segment in self.segments:
            segment.determine_need()

    def check_links(self):
        consolidated = []
        for segment in self.segments:
            segment.check_links()
            consolidated.extend(segment.consolidated_links)
        linked = []
        for a, b in consolidated:
            linked.append(a)
            linked.append(b)
        assert len(linked) == len(set(linked))

    def __repr__(self):
        display = "\n---\n".join([str(s) for s in self.segments])

        return display


def parse_checkpoints():
    if ANCIENT:
        checkpoints = ANCIENT_CHECKPOINTS_TABLE
    else:
        checkpoints = TOWER_CHECKPOINTS_TABLE

    def ent_text_to_ints(room, single=False):
        locid, entids = room.split(':')
        locid = int(locid)
        if '|' in entids:
            entids = entids.split('|')
        elif ',' in entids:
            entids = entids.split(',')
        elif '>' in entids:
            entids = entids.split('>')[:1]
        else:
            entids = [entids]
        entids = map(int, entids)
        if single:
            assert len(entids) == 1
            entids = entids[0]
        return locid, entids

    done, fixed, remove, oneway = [], [], [], []
    routes = [list([]) for _ in xrange(3)]
    for line in open(checkpoints):
        line = line.strip()
        if not line or line[0] == '#':
            continue
        if line[0] == 'R':
            rank = int(line[1:])
            for route in routes:
                route[-1].append(("R", rank))
        elif line[0] == '&':
            locid, entids = ent_text_to_ints(line[1:])
            for e in entids:
                fixed.append((locid, e))
        elif line[0] == '-':
            locid, entids = ent_text_to_ints(line[1:])
            for e in entids:
                remove.append((locid, e))
        elif '>>' in line:
            line = line.split('>>')
            line = [ent_text_to_ints(s, single=True) for s in line]
            first, second = tuple(line)
            oneway.append((first, second))
        else:
            if line.startswith("!"):
                line = line.strip("!")
                for route in routes:
                    route.append([])
            elif line.startswith("$"):
                line = line.strip("$")
                for route in routes:
                    subroute = route[-1]
                    head, tail = subroute[0], subroute[1:]
                    random.shuffle(tail)
                    route[-1] = [head] + tail
            else:
                random.shuffle(routes)
            rooms = line.split(',')
            chosenrooms = []
            for room in rooms:
                locid, entids = ent_text_to_ints(room)
                candidates = [(locid, entid) for entid in entids]
                candidates = [c for c in candidates if c not in done]
                chosen = random.choice(candidates)
                chosenrooms.append(chosen)
                done.append(chosen)
            for room, route in zip(chosenrooms, routes):
                route[-1].append(room)

    for first, second in oneway:
        done = False
        for route in routes:
            for subroute in route:
                if first in subroute:
                    index = subroute.index(first)
                    index = random.randint(1, index+1)
                    subroute.insert(index, second)
                    done = True
        if not done:
            raise Exception("Unknown oneway rule")

    for route in routes:
        for i in range(len(route)):
            route[i] = Segment(route[i])

    for index in range(len(routes)):
        routes[index] = Route(routes[index])

    FIXED_ENTRANCES.extend(fixed)
    REMOVE_ENTRANCES.extend(remove)
    return routes, fixed, remove


def assign_maps(routes):
    clusters = get_clusters()
    new_clusters = clusters
    for route in routes:
        for segment in route.segments:
            for cluster in segment.clusters:
                if cluster in new_clusters:
                    new_clusters.remove(cluster)

    # first phase - bare minimum
    max_new_maps = 23
    best_clusters = [c for c in new_clusters if len(c.entrances) >= 3]
    while True:
        random.shuffle(best_clusters)
        done_maps, done_clusters = set([]), set([])
        for cluster in best_clusters:
            chosen = None
            for route in routes:
                for segment in route.segments:
                    for inter in segment.intersegments:
                        if chosen is None or chosen.need < inter.need:
                            chosen = inter
            if chosen.need > 0:
                chosen.add_cluster(cluster, need=True)
                done_maps.add(cluster.locid)
                done_clusters.add(cluster.clusterid)
        if len(done_maps) <= max_new_maps:
            break
        else:
            for route in routes:
                for segment in route.segments:
                    segment.intersegments = [InterSegment()
                                             for _ in segment.intersegments]

    # second phase -supplementary
    random.shuffle(new_clusters)
    for cluster in new_clusters:
        if cluster.clusterid in done_clusters:
            continue
        if cluster.locid not in towerlocids:
            if (cluster.locid not in done_maps
                    and len(done_maps) >= max_new_maps):
                continue
            if (cluster.locid in done_maps and len(done_maps) >= max_new_maps
                    and get_location(cluster.locid).longentrances):
                continue
        if len(cluster.entrances) == 1:
            candidates = []
            for route in routes:
                for segment in route.segments:
                    for inter in segment.intersegments:
                        if inter.need < 0:
                            candidates.append(inter)
            if candidates:
                chosen = random.choice(candidates)
                chosen.add_cluster(cluster, need=True)
                done_maps.add(cluster.locid)
                done_clusters.add(cluster.clusterid)
        elif len(cluster.entrances) >= 2:
            route = random.choice(routes)
            segment = random.choice(route.segments)
            chosen = random.choice(segment.intersegments)
            chosen.add_cluster(cluster, need=True)
            done_maps.add(cluster.locid)
            done_clusters.add(cluster.clusterid)

    for route in routes:
        for segment in route.segments:
            segment.interconnect()


if __name__ == "__main__":
    from randomizer import get_monsters
    get_monsters(filename="program.rom")
    get_formations(filename="program.rom")
    get_fsets(filename="program.rom")
    get_locations(filename="program.rom")
    routes, fixed, remove = parse_checkpoints()
    #for route in routes:
    #    print route
    #    print

    for route in routes:
        route.determine_need()
    assign_maps(routes)
    for route in routes:
        route.check_links()
        print route
        print
        print