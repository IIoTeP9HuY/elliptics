# =============================================================================
# 2013+ Copyright (c) Alexey Ivanov <rbtz@ph34r.me>
# 2013+ Copyright (c) Kirill Smorodinnikov <shaitkir@gmail.com>
# All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# =============================================================================

"""
Wrappers for iterator and it's result container
"""

import sys
import os

from .utils.misc import logged_class, mk_container_name
from .etime import Time
from .range import IdRange
from collections import namedtuple

sys.path.insert(0, "bindings/python/")  # XXX
import elliptics


@logged_class
class IteratorResult(object):
    """
    Container for iterator results.
    Provides IteratorResultContainer wrapper.
    """

    def __init__(self,
                 address=None,
                 container=None,
                 tmp_dir="",
                 leave_file=False,
                 filename="",
                 range_id=0,
                 ):
        self.address = address
        self.container = container
        self.tmp_dir = tmp_dir
        self.__file = None
        self.leave_file = leave_file
        self.filename = filename
        self.range_id = range_id

    def __del__(self):
        if self.leave_file:
            return
        self.remove()

    def remove(self):
        try:
            if self.__file:
                os.unlink(self.__file.name)
        except Exception as e:
            self.log.error("Can't remove file: {0}: {1}".format(self.__file.name, e))

    def __len__(self):
        return len(self.container)

    def __iter__(self):
        return iter(self.container)

    def __nonzero__(self):
        return len(self)

    def append(self, record):
        self.container.append(record)

    def append_rr(self, record):
        self.container.append_rr(record)

    def sort(self):
        """Sorts results"""
        self.container.sort()

    def diff(self, other):
        """
        Computes diff between two sorted results. Returns container that consists of difference.
        """
        import hashlib
        filename = 'diff_' + hashlib.sha256(str(self.address)).hexdigest() + '-' + hashlib.sha256(str(other.address)).hexdigest()
        diff_container = IteratorResult.from_filename(filename,
                                                      address=other.address,
                                                      tmp_dir=self.tmp_dir
                                                      )
        self.container.diff(other.container, diff_container.container)
        return diff_container

    @classmethod
    def merge(cls, results, tmp_dir):
        """
        Merges diffs and split result by node owner:
            results contains diffs from all remote nodes
            Removes from results empty diffs
            If results is empty - skipping merge stage
            If results contains diffs only for 1 node - nothing to merge just copy this diffs
            Otherwise:
                for each node creates tuple (value, iterator, result) and combines it in the list:
                    Value - record from the top of node diffs.
                    Iterator - iterator of node diffs.
                    results - resulting container of merged diffs.
                1.  Goes through tuples and find tuple with minimum key and maximum timestamp in value
                2.  Value from the tuple appends in corresponding result container.
                3.  Goes through tuples again and for tuple with a key equal to minimum key, gets new record from iterator while it key == minimum or end of node diffs is reached.
                4.  If for some tuple all node diffs are processed - adds number of the tuple into remove list
                5.  After that removes from tuple list all tuples from remove list
                6.  Repeates step 1-6 while tuple list isn't empty
        """
        results = [d for d in results if d and len(d) != 0]
        if len(results) == 1:
            import shutil
            diff = results[0]
            filename = os.path.join(tmp_dir, mk_container_name(diff.address, "merge_"))
            shutil.copyfile(diff.filename, filename)
            return [cls.load_filename(filename,
                                      address=diff.address,
                                      is_sorted=True,
                                      tmp_dir=tmp_dir,
                                      leave_file=True
                                      )]
        elif len(results) != 0:
            return cls.__merge__(results, tmp_dir)
        return None

    @classmethod
    def combine(cls, results, tmp_dir):
        results = [d for d in results if d and len(d) != 0]
        if len(results) == 1:
            import shutil

    @classmethod
    def __merge__(cls, results, tmp_dir):
        import heapq
        ret = []
        heap = []
        for d in results:
            try:
                heapq.heappush(heap,
                               MergeData(d,
                                         IteratorResult.from_filename(os.path.join(tmp_dir, mk_container_name(d.address, "merge_")),
                                                                      address=d.address,
                                                                      tmp_dir=tmp_dir,
                                                                      leave_file=True
                                                                      )))
            except StopIteration:
                pass

        while len(heap):
            min_data = heapq.heappop(heap)
            min_data.container.append_rr(min_data.value)
            same_datas = [min_data]
            while len(heap) and min_data.value.key == heap[0].value.key:
                same_datas.append(heapq.heappop(heap))
            for i in same_datas:
                try:
                    i.next()
                    heapq.heappush(heap, i)
                except StopIteration:
                    ret.append(i.container)

        return ret

    @classmethod
    def from_filename(cls, filename, tmp_dir="", **kwargs):
        """
        Creates iterator result from filename
        """
        if tmp_dir:
            filename = os.path.join(tmp_dir, filename)
        container_file = open(filename, 'w+')
        result = cls.from_fd(container_file.fileno(), tmp_dir=tmp_dir, filename=filename, **kwargs)
        result.__file = container_file  # Save it from python's gc
        return result

    @classmethod
    def load_filename(cls, filename, is_sorted=False, tmp_dir="", **kwargs):
        """
        Creates iterator result from filename
        """
        if tmp_dir:
            filename = os.path.join(tmp_dir, filename)
        if not os.path.exists(filename):
            return None
        container_file = open(filename, 'r+')
        container_file.seek(0, 2)
        result = cls.from_info(container_file.fileno(), is_sorted, container_file.tell(), tmp_dir=tmp_dir, filename=filename, **kwargs)
        result.__file = container_file  # Save it from python's gc
        return result

    @classmethod
    def from_info(cls, fd, is_sorted, position, **kwargs):
        result = cls(**kwargs)
        result.container = elliptics.IteratorResultContainer(fd, is_sorted, position)
        return result

    @classmethod
    def from_fd(cls, fd, **kwargs):
        """
        Creates iterator result from fd
        """
        result = cls(**kwargs)
        result.container = elliptics.IteratorResultContainer(fd)
        return result


@logged_class
class Iterator(object):
    """
    Wrapper on top of elliptics new iterator and it's result container
    """

    def __init__(self, node, group, separately=False):
        self.session = elliptics.Session(node)
        self.session.groups = [group]
        self.separately = separately

    def get_key_range_id(self, key):
        if not self.separately:
            return 0

        stop = len(self.ranges)
        start = 0

        while start < stop:
            curr = (stop + start) / 2
            curr_range = self.ranges[curr]
            check = curr_range.check_key(key)
            if check == 0:
                return curr_range.range_id
            elif check < 0:
                stop = curr
            else:
                start = curr
        self.log.debug("Not found range for %s", repr(key))

    def start(self,
              eid=IdRange.ID_MIN,
              itype=elliptics.iterator_types.network,
              flags=elliptics.iterator_flags.key_range | elliptics.iterator_flags.ts_range,
              key_ranges=(IdRange(IdRange.ID_MIN, IdRange.ID_MAX),),
              timestamp_range=(Time.time_min().to_etime(), Time.time_max().to_etime()),
              tmp_dir='/var/tmp',
              address=None,
              leave_file=False,
              batch_size=1024):
        assert itype == elliptics.iterator_types.network, "Only network iterator is supported for now"
        assert flags & elliptics.iterator_flags.data == 0, "Only metadata iterator is supported for now"
        assert len(key_ranges) > 0, "There should be at least one iteration range."
        self.ranges = key_ranges

        try:
            results = dict()
            if self.separately:
                for range in key_ranges:
                    prefix = 'iterator_{0}_'.format(range.range_id)
                    filename = os.path.join(tmp_dir,
                                            mk_container_name(address=address,
                                                              prefix=prefix))
                    results[range.range_id] = IteratorResult.from_filename(filename=filename,
                                                                           address=address,
                                                                           tmp_dir=tmp_dir,
                                                                           leave_file=leave_file)
            else:
                filename = os.path.join(tmp_dir, mk_container_name(address))
                results[0] = IteratorResult.from_filename(filename=filename,
                                                          address=address,
                                                          tmp_dir=tmp_dir,
                                                          leave_file=leave_file)

            ranges = [IdRange.elliptics_range(start, stop) for start, stop in key_ranges]
            records = self.session.start_iterator(eid,
                                                  ranges,
                                                  itype,
                                                  flags,
                                                  timestamp_range[0],
                                                  timestamp_range[1])
            filtered_keys = 0
            iterated_keys = 0
            total_keys = 0

            for num, record in enumerate(records):
                # TODO: Here we can add throttling
                if record.status != 0:
                    raise RuntimeError("Iteration status check failed: {0}".format(record.status))
                #skipping keepalive responses
                if record.response.status == 0:
                    filtered_keys = num + 1
                iterated_keys = record.response.iterated_keys
                total_keys = record.response.total_keys

                if iterated_keys % batch_size == 0:
                    yield (filtered_keys, iterated_keys, total_keys)
                if record.response.status != 0:
                    continue
                results[self.get_key_range_id(record.response.key)].append(record)

            elapsed_time = records.elapsed_time()
            self.log.debug("Time spended for iterator: {0}/{1}".format(elapsed_time.tsec, elapsed_time.tnsec))
            yield (filtered_keys, iterated_keys, total_keys)
            if self.separately:
                yield results
            else:
                yield results[0]
        except Exception as e:
            self.log.error("Iteration failed: {0}".format(e))
            yield None


    @classmethod
    def iterate_with_stats(cls, node, eid, timestamp_range,
                           key_ranges, tmp_dir, address, batch_size,
                           stats, leave_file=False,
                           separately=False):
        iterator = cls(node, address.group_id, separately)
        result = iterator.start(eid=eid,
                                timestamp_range=timestamp_range,
                                key_ranges=key_ranges,
                                tmp_dir=tmp_dir,
                                address=address,
                                batch_size=batch_size,
                                leave_file=leave_file,
                                )
        result_len = 0
        for it in result:
            if it is None:
                result = None
                break
            elif type(it) in [dict, IteratorResult]:
                result = it
                break

            filtered_keys, iterated_keys, total_keys = it
            result_len = filtered_keys
            stats.set_counter('filtered_keys', filtered_keys)
            stats.set_counter('iterated_keys', iterated_keys)
            stats.set_counter('total_keys', total_keys)

        return result, result_len


class MergeData(object):
    """
    Assist class for IteratorResult.__merge__
    """

    def __init__(self, result, container):
        self.iter = iter(result)
        self.container = container
        self.value = None
        self.next_value = None
        self.address = result.address
        self.next()

    def __cmp__(self, other):
        cmp_res = cmp(self.value.key, other.value.key)

        if cmp_res == 0:
            cmp_res = cmp(other.value.timestamp, self.value.timestamp)

            if cmp_res == 0:
                cmp_res = cmp(self.value.size, other.value.size)

        return cmp_res

    def next(self):
        if self.iter is None:
            raise StopIteration

        if self.value is None:
            self.value = next(self.iter)
        else:
            self.value = self.next_value

        try:
            self.next_value = next(self.iter)
        except StopIteration:
            self.next_value = None
            self.iter = None
            return

        try:
            while cmp(self.value.key, self.next_value.key) == 0:
                if cmp(self.value.timestamp, self.next_value.timestamp) < 0:
                    self.value = self.next_value
                self.next_value = next(self.iter)
        except StopIteration:
            self.next_value = None
            self.iter = None


KeyInfo = namedtuple('KeyInfo', 'address, timestamp, size, user_flags')
