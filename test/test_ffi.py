import unittest
import logging
from time import time
from beat import ffi
from beat.heart import DynamicTarget

import numpy as num

from pyrocko import util, gf, model

import theano.tensor as tt
from theano import function
from theano import config as tconfig

km = 1000.

logger = logging.getLogger('test_ffi')


class FFITest(unittest.TestCase):

    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)

        nsamples = 10
        ntargets = 3
        npatches = 4
        nrisetimes = 5
        nstarttimes = 7
        nsamples = 20

        lats = [10., 35., -34.]
        lons = [190., 260., 10.]

        stations = [model.Station(
            lat=lat, lon=lon) for lat, lon in zip(lats, lons)]

        targets = [DynamicTarget(store_id='Test') for i in range(ntargets)]

        self.gfs = ffi.SeismicGFLibrary(
            targets=targets, stations=stations, component='uperp')
        self.gfs.setup(ntargets, npatches, nrisetimes, nstarttimes, nsamples)

        tracedata = num.tile(
            num.arange(nsamples), nstarttimes).reshape((nstarttimes, nsamples))
        for target in targets:
            for patchidx in range(npatches):
                for risetimeidx in range(nrisetimes):
                    starttimeidxs = range(nstarttimes)

                    self.gfs.put(
                        tracedata * risetimeidx, target, patchidx, risetimeidx,
                        starttimeidxs)

    def test_gf_setup(self):
        print self.gfs
        # print self.gfs._gfmatrix

    def test_stacking(self):
        def reference_numpy(gfs, risetimeidxs, starttimeidxs, slips):
            u2d = num.tile(
                slips, gfs.nsamples).reshape(gfs.nsamples, gfs.npatches)
            t0 = time()
            patchidxs = num.arange(gfs.npatches)
            d = gfs._gfmatrix[:, patchidxs, risetimeidxs, starttimeidxs, :]
            print d, d.shape
            d1 = d.reshape(
                (self.gfs.ntargets, self.gfs.npatches, self.gfs.nsamples))
            out_array = num.einsum('ijk->ik', d1 * u2d.T)
            t1 = time()
            logger.info('Calculation time numpy einsum: %f', (t1 - t0))
            return out_array

        def prepare_theano(gfs):
            theano_rts = tt.vector('rt_indxs', dtype='int16')
            theano_stts = tt.vector('start_indxs', dtype='int16')
            theano_slips = tt.dvector('slips')
            gfs.init_optimization_mode()
            return theano_rts, theano_stts, theano_slips

        def theano_batched_dot(gfs, risetimeidxs, starttimeidxs, slips):
            theano_rts, theano_stts, theano_slips = prepare_theano(gfs)

            outstack = gfs.stack_all(
                starttimeidxs=theano_stts,
                risetimeidxs=theano_rts,
                slips=theano_slips)

            t0 = time()
            f = function([theano_slips, theano_rts, theano_stts], [outstack])
            t1 = time()
            logger.info('Compile time theano batched_dot: %f', (t1 - t0))

            out_array = f(slips, risetimeidxs, starttimeidxs)
            t2 = time()
            logger.info('Calculation time batched_dot: %f', (t2 - t1))
            return out_array

        def theano_for_loop(gfs, risetimeidxs, starttimeidxs, slips):
            theano_rts, theano_stts, theano_slips = prepare_theano(gfs)

            patchidxs = range(gfs.npatches)

            outstack = tt.zeros_like(
                (gfs.ntargets, gfs.nsamples), tconfig.floatX)
            for i, target in enumerate(gfs.targets):
                synths = gfs.stack(
                    target, patchidxs, starttimeidxs, risetimeidxs, slips)
                tt.set_subtensor(outstack[i:i + 1, 0:gfs.nsamples], synths)

            t0 = time()
            f = function([theano_slips, theano_rts, theano_stts], [outstack])
            t1 = time()
            logger.info('Compile time theano for loop: %f', (t1 - t0))

            out_array = f(slips, risetimeidxs, starttimeidxs)
            t2 = time()
            logger.info('Calculation time for loop: %f', (t2 - t1))
            return out_array

        risetimeidxs = num.random.randint(
            low=0, high=self.gfs.nrisetimes,
            size=self.gfs.npatches, dtype='int16')
        starttimeidxs = num.random.randint(
            low=0, high=self.gfs.nstarttimes,
            size=self.gfs.npatches, dtype='int16')
        slips = num.random.random(self.gfs.npatches)

        outnum = reference_numpy(self.gfs, risetimeidxs, starttimeidxs, slips)
        outtheanobatch = theano_batched_dot(
            self.gfs, risetimeidxs, starttimeidxs, slips)
        outtheanofor = theano_for_loop(
            self.gfs, risetimeidxs, starttimeidxs, slips)

        num.testing.assert_allclose(outnum, outtheanobatch, rtol=0., atol=1e-6)
        num.testing.assert_allclose(outnum, outtheanofor, rtol=0., atol=1e-6)


if __name__ == '__main__':
    util.setup_logging('test_ffi', 'info')
    unittest.main()