"""When the best upload cannot be fetched (an age gate, taken down), the next best one is tried (P1-01)."""
import unittest

from encore_fetch.download import DownloadError
from encore_fetch.jobs import song_key
from encore_fetch.lean import LeanResolver, rank
from encore_fetch.resolve import Candidate, Scored, Want

from tests.test_lean import RecordedSearcher
from tests.test_pipeline import AUTH, FakeDownloader, PipelineTest

WANT = Want("Opeth", "Windowpane", "Damnation", 467)


def upload(video_id, title="Windowpane", channel="Opeth - Topic", duration=467):
    return Candidate(video_id, title, channel, duration, True)


class RankTest(unittest.TestCase):
    def test_every_acceptable_candidate_comes_back_best_first(self):
        ranked = rank(WANT, [upload("aaaaaaaaaaa", "Windowpane (Live)", "SomeFan", 470), upload("bbbbbbbbbbb"),
                             upload("ccccccccccc", "Unrelated Song", "Nobody", 100)])
        self.assertEqual([s.candidate.video_id for s in ranked][0], "bbbbbbbbbbb")
        self.assertNotIn("ccccccccccc", [s.candidate.video_id for s in ranked])

    def test_a_recorded_search_gives_more_than_one_choice(self):
        resolver = LeanResolver(RecordedSearcher())
        self.addCleanup(resolver._pool.shutdown)
        ranked = resolver.resolve_ranked(Want("Mishary Alafasy", "Surah Al-Baqarah", None, 8481))
        self.assertGreater(len(ranked), 1)
        self.assertGreaterEqual(ranked[0].score, ranked[1].score)

    def test_resolve_is_the_first_of_the_ranked_answer(self):
        resolver = LeanResolver(RecordedSearcher())
        self.addCleanup(resolver._pool.shutdown)
        want = Want("Nas", "N.Y. State of Mind", "Illmatic", 294)
        self.assertEqual(resolver.resolve(want).candidate.video_id, resolver.resolve_ranked(want)[0].candidate.video_id)


class RankedSearcher:
    """A resolver that offers a ranked list, like LeanResolver."""

    def __init__(self, *ids):
        self.ranked = [Scored(upload(i), 10.0 - n, ("fake",)) for n, i in enumerate(ids)]
        self.calls = 0

    def resolve_ranked(self, want):
        self.calls += 1
        return list(self.ranked)

    def resolve(self, want):
        return self.ranked[0] if self.ranked else None


class PickyDownloader(FakeDownloader):
    """Refuses some uploads at the extraction step, like an age-gated or removed video."""

    def __init__(self, refuse):
        super().__init__()
        self.refuse = dict(refuse)

    def extract(self, video_id, info):
        self.extracted.append(video_id)
        if video_id in self.refuse:
            raise DownloadError(self.refuse[video_id])
        info.parent.mkdir(parents=True, exist_ok=True)
        info.write_text("{}", encoding="utf-8")


class JobTriesTheNextUploadTest(PipelineTest):
    def run_with(self, searcher, downloader):
        m = self.manager(downloader=downloader)
        m._resolver = searcher
        return m, m.submit(AUTH, self.req)

    def test_an_age_gated_first_choice_falls_through_to_the_next(self):
        downloader = PickyDownloader({"aaaaaaaaaaa": "age_restricted"})
        m, job = self.run_with(RankedSearcher("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"), downloader)
        self.assertEqual(job.state, "ready", job.view())
        self.assertEqual(downloader.extracted, ["aaaaaaaaaaa", "bbbbbbbbbbb"])
        self.assertEqual(downloader.calls, ["bbbbbbbbbbb"])

    def test_the_working_upload_is_the_one_remembered_for_next_time(self):
        downloader = PickyDownloader({"aaaaaaaaaaa": "unavailable"})
        m, _ = self.run_with(RankedSearcher("aaaaaaaaaaa", "bbbbbbbbbbb"), downloader)
        remembered = m._resolutions.get(song_key("Opeth", "Windowpane", 467))
        self.assertEqual(remembered["video_id"], "bbbbbbbbbbb")

    def test_a_gone_remembered_upload_followed_by_a_refused_new_first_choice_still_finds_one(self):
        # What happened on the real server: an earlier failure had left the age-gated album track as the remembered upload;
        # the new search ranks it first again, and only the next best upload can be fetched.
        downloader = PickyDownloader({"aaaaaaaaaaa": "age_restricted"})
        m = self.manager(downloader=downloader)
        m._resolver = RankedSearcher("aaaaaaaaaaa", "bbbbbbbbbbb")
        m._resolutions.put(song_key("Opeth", "Windowpane", 467), "aaaaaaaaaaa", "Windowpane", 467)
        job = m.submit(AUTH, self.req)
        self.assertEqual(job.state, "ready", job.view())
        self.assertEqual(downloader.extracted, ["aaaaaaaaaaa", "aaaaaaaaaaa", "bbbbbbbbbbb"])

    def test_when_every_choice_is_refused_the_last_reason_is_the_answer(self):
        downloader = PickyDownloader({"aaaaaaaaaaa": "age_restricted", "bbbbbbbbbbb": "unavailable"})
        m, job = self.run_with(RankedSearcher("aaaaaaaaaaa", "bbbbbbbbbbb"), downloader)
        self.assertEqual(job.state, "failed")
        self.assertEqual(job.error, "unavailable")

    def test_a_block_is_not_a_reason_to_try_other_uploads(self):
        downloader = PickyDownloader({"aaaaaaaaaaa": "blocked"})
        m, job = self.run_with(RankedSearcher("aaaaaaaaaaa", "bbbbbbbbbbb"), downloader)
        self.assertEqual(set(downloader.extracted), {"aaaaaaaaaaa"})  # YouTube refusing us is not about this upload
        self.assertEqual(job.state, "failed")

    def test_a_resolver_without_a_ranked_answer_still_works(self):
        m = self.manager()  # the plain FakeSearcher of the pipeline tests
        job = m.submit(AUTH, self.req)
        self.assertEqual(job.state, "ready", job.view())


if __name__ == "__main__":
    unittest.main()
