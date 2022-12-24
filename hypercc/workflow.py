"""
Implements the HyperCanny workflow for climate data.
"""
import os
from pathlib import Path

import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import numpy as np
from scipy import ndimage

from hyper_canny import cp_edge_thinning, cp_double_threshold

from .data.data_set import DataSet
from .units import unit, month_index
from .filters import gaussian_filter, sobel_filter, taper_masked_area
from .calibration import calibrate_sobel
from .plotting import plot_signal_histogram, plot_plate_carree

def run(workflow):
    return workflow


def run_single(workflow):
    return workflow


def open_data_files(config):
    """Open data files from the settings given in `config`.

    :param config: namespace object (as returned by argparser)
    :return: DataSet
    """
    data_set = DataSet.cmip6(
        path=config.data_folder,
        model=config.model,
        variable=config.variable,
        scenario=config.scenario,
        realization=config.realization,
        frequency=config.frequency,
        extension=config.extension
    )

    return data_set


def open_pi_control(config):
    if config.pi_control_folder:
        pi_control_folder = config.pi_control_folder
    else:
        pi_control_folder = config.data_folder

    control_set = DataSet.cmip6(
        path=pi_control_folder,
        model=config.model,
        variable=config.variable,
        scenario='piControl',
        extension=config.extension,
        frequency=config.frequency,
        realization=config.realization)

    return control_set


def open_data_files_cmip5(config):
    """Open data files from the settings given in `config`.

    :param config: namespace object (as returned by argparser)
    :return: DataSet
    """
    data_set = DataSet.cmip5(
        path=config.data_folder,
        model=config.model,
        variable=config.variable,
        scenario=config.scenario,
        realization=config.realization,
        extension=config.extension
    )

    return data_set


def open_pi_control_cmip5(config):
    if config.pi_control_folder:
        pi_control_folder = config.pi_control_folder
    else:
        pi_control_folder = config.data_folder

    control_set = DataSet.cmip5(
        path=pi_control_folder,
        model=config.model,
        variable=config.variable,
        scenario='piControl',
        extension=config.extension,
        realization=config.realization)

    return control_set


def select_month(config, data_set):
    month = month_index(config.month)
    return data_set[month::12]


def annual_mean(data_set):
    print("Computing annual mean.")
    return data_set.annual_mean()


def compute_calibration(config, data_set):
    quartile = ['min', '1st', 'median', '3rd', 'max'] \
        .index(config.calibration_quartile)
    sigma_t, sigma_x = get_sigmas(config)
    sobel_scale = float(config.sobel_scale[0]) * unit(config.sobel_scale[1])
    sobel_delta_t = 1.0 * unit.year
    sobel_delta_x = sobel_delta_t * sobel_scale

    data = data_set.data
    box = data_set.box

    print("Settings for calibration:")
    print("    sigma_x: ", sigma_x)
    print("    sigma_t: ", sigma_t)
    print("    delta_x: ", sobel_delta_x)
    print("    delta_t: ", sobel_delta_t)

    if config.taper and isinstance(data, np.ma.core.MaskedArray):
        print("    tapering on")
        taper_masked_area(data, [0, 5, 5], 50)

    smooth_data = gaussian_filter(box, data, [sigma_t, sigma_x, sigma_x])
    calibration = calibrate_sobel(quartile, box, smooth_data, sobel_delta_t, sobel_delta_x)

    return calibration


def get_calibration_factor(config, calibration):
    quartile = ['min', '1st', 'median', '3rd', 'max'] \
        .index(config.calibration_quartile)
    gamma = calibration['gamma'][quartile]
    #print("Calibration gamma[{}] = {}"
    #      .format(config.calibration_quartile, gamma))
    return gamma


def get_sigmas(config):
    sigma_t = float(config.sigma_t[0]) * unit(config.sigma_t[1])
    sigma_x = float(config.sigma_x[0]) * unit(config.sigma_x[1])
    return sigma_t, sigma_x


def get_sobel_weights(config, calibration):
    sobel_scale = float(config.sobel_scale[0]) * unit(config.sobel_scale[1])
    gamma = get_calibration_factor(config, calibration)
    sobel_delta_t = 1.0 * unit.year
    sobel_delta_x = sobel_delta_t * sobel_scale * gamma
    return [sobel_delta_t, sobel_delta_x, sobel_delta_x]


def generate_signal_plot(
        config, calibration, box, sobel_data, title, filename):
    lower, upper = get_thresholds(config, calibration)
    fig = plot_signal_histogram(box, 1 / sobel_data[3], lower, upper)
    fig.suptitle(title, fontsize=20)
    try:
        fig.savefig(str(filename), bbox_inches='tight')
    except ValueError:
        # save some mock data to prevent crashing of program
        fig = plt.figure()
        plt.plot([0, 1], [0, 1])
        fig.savefig(str(filename), bbox_inches='tight')
    return Path(filename)


def maximum_suppression(sobel_data):
    print("transposing data")
    trdata = sobel_data.transpose([3, 2, 1, 0]).copy()
    print("applying thinning")
    mask = cp_edge_thinning(trdata)
    return mask.transpose([2, 1, 0])


def get_thresholds(config, calibration):
    gamma = get_calibration_factor(config, calibration)
    mag_quartiles = np.sqrt(
        (calibration['distance'] * gamma)**2 + calibration['time']**2)

    ref_values = {
        'pi-control-3': mag_quartiles[3],
        'pi-control-max': mag_quartiles[4],
    }

    ref_lower=ref_values[config.lower_threshold_ref]
    ref_upper=ref_values[config.upper_threshold_ref]

    frac_lower=float(config.lower_threshold_frac[0])
    frac_upper=float(config.upper_threshold_frac[0])

    return ref_lower*frac_lower, ref_upper*frac_upper


def hysteresis_thresholding(config, sobel_data, mask, calibration):
    lower, upper = get_thresholds(config, calibration)
    print('    thresholds:', lower, upper)
    new_mask = cp_double_threshold(
        sobel_data.transpose([3, 2, 1, 0]).copy(),
        mask.transpose([2, 1, 0]),
        1. / upper,
        1. / lower)
    return new_mask.transpose([2, 1, 0])


def apply_mask_to_edges(edges, mask, time_margin):
    edges[:time_margin] = 0
    edges[-time_margin:] = 0
    return edges * ~mask


def transfer_magnitudes(x, y):
    x[3] = y[3]
    return x


def max_signal(sobel_data):
    """Compute the maximum signal."""
    return 1. / sobel_data[-1].min()


def compute_canny_edges(config, data_set, calibration):
    print("computing canny edges")
    data = data_set.data
    box = data_set.box

    sigma_t, sigma_x = get_sigmas(config)
    weights = get_sobel_weights(config, calibration)
    print("    calibrated weights:",
          ['{:~P}'.format(w) for w in weights])

    if config.taper and isinstance(data, np.ma.core.MaskedArray):
        print("    tapering")
        taper_masked_area(data, [0, 5, 5], 50)

    smooth_data = gaussian_filter(box, data, [sigma_t, sigma_x, sigma_x])
    sobel_data = sobel_filter(box, smooth_data, weight=weights)

    max_signal_value = 1 / sobel_data[-1].min()

    gamma = get_calibration_factor(config, calibration)
    mag_quartiles = np.sqrt(
        (calibration['distance'] * gamma)**2 + calibration['time']**2)
    max_signal_value_piC=mag_quartiles[4]
    lower, upper = get_thresholds(config, calibration)
    print("maximum signal in control:", max_signal_value_piC)
    print("maximum signal in data:", max_signal_value)
    print("upper threshold:", upper)
    if max_signal_value < upper:
        raise ValueError("Maximum signal below upper threshold, no need to continue.");

    pixel_sobel = sobel_filter(box, smooth_data, physical=False)
    pixel_sobel = transfer_magnitudes(pixel_sobel, sobel_data)
    sobel_maxima = maximum_suppression(pixel_sobel)

    if isinstance(data, np.ma.core.MaskedArray):
        sobel_maxima = apply_mask_to_edges(sobel_maxima, data.mask, 10)

    edges = hysteresis_thresholding(config, sobel_data, sobel_maxima, calibration)

    return dict(sobel=sobel_data, edges=edges)


def compute_maxTgrad(canny):
    tgrad = canny['sobel'][0]/canny['sobel'][3]       # unit('1/year');
    tgrad_residual = tgrad - np.mean(tgrad, axis=0)   # remove time mean
    maxm = canny['edges'].max(axis=0)		      # mask
    maxTgrad = np.max(abs(tgrad_residual), axis=0)    # maximum of time gradient
    maxTgrad = maxTgrad * maxm
    maxTgrad[np.isnan(maxTgrad)]=0                    # can be nan when var is constant
    indices_mask=np.where(maxTgrad>np.max(maxTgrad))  # set missing values to 0
    maxTgrad[indices_mask]=0                          # otherwise they show on map
    return maxTgrad

### There are many possible ways to quantify abruptness.
# This one has been labeled "measure 15j" during the testing:
def compute_measure15j(mask, years, data, cutoff_length, chunk_max_length, chunk_min_length):
    from scipy import stats

    idx = np.where(mask)
    indices=np.asarray(idx)

    measure15j_3d=mask*0.0

    shapeidx=np.shape(idx)
    nofresults=shapeidx[1]

    for result in range(nofresults):
        [dim0,dim1,dim2]=indices[:,result]

        if mask[dim0, dim1, dim2] == 1:
            index=dim0
            if ( index-cutoff_length >= 0 ) and ( index + cutoff_length + 1 <= np.size(data,axis=0) ):

                # determine last index of first chunk, and first index of second chunk
                # this takes into account how many points aroung the abrupt shift under
                # consideration are removed, and whether there are other abrupt shifts
                #in the vicinity

                # first, remove cutoff length (called ctrans in paper)
                chunk1_data=data[0:index-cutoff_length,dim1,dim2]
                chunk2_data=data[index+cutoff_length+1:,dim1,dim2]
                chunk1_years=years[0:index-cutoff_length]
                chunk2_years=years[index+cutoff_length+1:]
                chunk1_mask=mask[0:index-cutoff_length,dim1,dim2]
                chunk2_mask=mask[index+cutoff_length+1:,dim1,dim2]

                if np.size(chunk1_data) > chunk_max_length:
                    chunk1_start=np.size(chunk1_data)-chunk_max_length
                else:
                    chunk1_start=0
                if np.size(chunk2_data) > chunk_max_length:
                    chunk2_end=chunk_max_length
                else:
                    chunk2_end=np.size(chunk2_data)

                chunk1_data_short=chunk1_data[chunk1_start:]
                chunk2_data_short=chunk2_data[0:chunk2_end]
                chunk1_mask_short=chunk1_mask[chunk1_start:]
                chunk2_mask_short=chunk2_mask[0:chunk2_end]
                chunk1_years_short=chunk1_years[chunk1_start:]-years[dim0]
                chunk2_years_short=chunk2_years[0:chunk2_end]-years[dim0]


                # check if there are other edges in these chunks, and cut them off
                if np.sum(chunk1_mask_short) > 0:
                    #print("There are other edges in chunk 1")
                    index_edges = np.where(chunk1_mask_short)   # locate all other edges in chunk 1
                    index_edge=np.max(index_edges)        # take the last one (closest to abrupt shift under consideration here)
                    if index_edge + cutoff_length >= np.size(chunk1_data_short):   # also consider the cutoff length for that other edge
                        chunk1_data_short=[]
                    else:
                        chunk1_data_short=chunk1_data_short[index_edge+cutoff_length:]
                        chunk1_years_short=chunk1_years_short[index_edge+cutoff_length:]

                if np.sum(chunk2_mask_short) > 0:
                    #print("There are other edges in chunk 2")
                    index_edges = np.where(chunk2_mask_short)   # locate all other edges in chunk 1
                    index_edge=np.min(index_edges)        # take the last one (closest to abrupt shift under consideration here)
                    if index_edge - cutoff_length < 0 :   # also consider the cutoff length for that other edge
                        chunk2_data_short=[]
                    else:
                        chunk2_data_short=chunk2_data_short[0:index_edge-cutoff_length]
                        chunk2_years_short=chunk2_years_short[0:index_edge-cutoff_length]


                N1=np.size(chunk1_data_short)
                N2=np.size(chunk2_data_short)

                if not ((N1 < chunk_min_length) or (N2 < chunk_min_length)):

                    slope_chunk1, intercept_chunk1, r_value, p_value, std_err = stats.linregress(chunk1_years_short, chunk1_data_short)
                    chunk1_regline=intercept_chunk1 + slope_chunk1*chunk1_years_short

                    slope_chunk2, intercept_chunk2, r_value, p_value, std_err = stats.linregress(chunk2_years_short, chunk2_data_short)
                    chunk2_regline=intercept_chunk2 + slope_chunk2*chunk2_years_short

                    mean_std=(np.nanstd(chunk1_data_short)+np.nanstd(chunk2_data_short))/2

                    if mean_std == 0:
                        mean_chunk1=np.mean(chunk1_data_short)
                        mean_chunk2=np.mean(chunk2_data_short)
                        if mean_chunk1 == mean_chunk2:
                            measure15j_3d[dim0,dim1,dim2]=0
                        else:
                            measure15j_3d[dim0,dim1,dim2]=9e99
                    else:
                        measure15j_3d[dim0,dim1,dim2]=abs(intercept_chunk1-intercept_chunk2)/mean_std

    measure15j=np.max(measure15j_3d,axis=0)
    measure15j[np.isnan(measure15j)]=0
    # indices_mask=np.where(measure15j>np.max(measure15j))  # set missing values to 0
    indices_mask=np.where(measure15j>100)  # set missing values to 0
    measure15j[indices_mask]=0                            # otherwise they show on map

    return {
        'measure15j_3d': measure15j_3d,
	'measure15j':    measure15j
    }


def write_netcdf_2d(field, filename):
    import netCDF4
    ncfile = netCDF4.Dataset(filename, "a", format="NETCDF4")
    ncfile.variables['outdata'][0,:,:]=field
    ncfile.close()


def write_netcdf_3d(field, filename):
    import netCDF4
    ncfile = netCDF4.Dataset(filename, "a", format="NETCDF4")
    ncfile.variables['outdata'][:,:,:]=field
    ncfile.close()


def write_ts(ts, filename):
   file = open(str(filename),'w')
   np.savetxt(file, ts, fmt='%s', delimiter=" ")
   file.close()


def generate_standard_map_plot(box, field, title, filename):
    import matplotlib
    my_cmap = matplotlib.cm.get_cmap('rainbow')
    my_cmap.set_under('w')
    if np.max(abs(field)) > 0:
        fig = plot_plate_carree(
            box, field, transform=ccrs.PlateCarree(), patch_greenwich=False,
            cmap=my_cmap, vmin=1e-30
        )
    else:
        fig = plot_plate_carree(
            box, field, transform=ccrs.PlateCarree(), patch_greenwich=False,
            cmap=my_cmap, vmin=-1e-30, vmax=1e-30
        )

    # fig = plt.figure(figsize=(20, 10))
    # lon = box.lon.copy()
    # lat = box.lat.copy()
    #
    #
    # ax = fig.add_subplot(111, projection=ccrs.PlateCarree())
    # pcm = ax.contourf(lon, lat, field, transform=ccrs.PlateCarree())
    # ax.coastlines()
    # fig.colorbar(pcm)
    # plt.close()

    fig.suptitle(title, fontsize=20)
    fig.savefig(str(filename), bbox_inches='tight')
    return Path(filename)


def generate_timeseries_plot(config, box, data, abruptness, abruptness_3d, title, filename):
    import matplotlib
    sigma_t, sigma_x = get_sigmas(config)
    if np.max(abs(abruptness)) > 0:
        lonind=np.nanargmax(np.nanmax(abruptness, axis=0))
        latind=np.nanargmax(np.nanmax(abruptness, axis=1))
        ts=data[:,latind,lonind]
        years = np.array([dd.year for dd in box.dates])
        fig = plt.figure()
        ax=plt.subplot(111)

        ### smoothed data
        sigma_t, sigma_x = get_sigmas(config)
        if config.taper and isinstance(data, np.ma.core.MaskedArray):
            taper_masked_area(data, [0, 5, 5], 50)
        smooth_data = gaussian_filter(box, data, [sigma_t, sigma_x, sigma_x])

        ts_smooth=smooth_data[:,latind,lonind]

        ax.plot(years, ts, 'k', years, ts_smooth, 'b--')

        ### show abruptness of that time series
        abruptness_max=abruptness[latind,lonind]
        ymin=np.min(ts)
        ymax=np.max(ts)
        xmin=np.min(years)
        xmax=np.max(years)
        xrange=xmax-xmin
        yrange=ymax-ymin
        ypos=ymax-0.04*yrange
        xpos=xmin+0.01*xrange
        ax.text(xpos,ypos,'abruptness: '+ '{:f}'.format(abruptness_max),color='r',size=16)

        ## show year of the most abrupt event as vertical red line
        index=np.where(abruptness_3d[:,latind,lonind]==abruptness_max)
        ax.axvline(x=years[index], ymin=0, ymax=1, color='r', linestyle="--")

        fig.suptitle(title, fontsize=20)
        ax.set_xlabel('year', fontsize=20)
        ax.set_ylabel('data', fontsize=20)
        fig.savefig(str(filename), bbox_inches='tight')
        return Path(filename)


def label_regions(mask, min_size=0):
    labels, n_features = ndimage.label(
        mask, ndimage.generate_binary_structure(3, 3))
    big_enough = [x for x in range(1, n_features+1)
                  if (labels == x).sum() > min_size]
    return dict(
        n_features=n_features,
        regions=np.where(np.isin(labels, big_enough), labels, 0),
        labels=big_enough
    )


def generate_region_plot(box, mask, title, filename, min_size=0):
    import matplotlib
    my_cmap = matplotlib.cm.get_cmap('rainbow')
    my_cmap.set_under('w')
    labels, n_features = ndimage.label(
        mask, ndimage.generate_binary_structure(3, 3))
    print('    n_features:', n_features)
    if n_features > 0:
        big_enough = [x for x in range(1, n_features+1)
        	          if (labels == x).sum() > min_size]
        regions = np.where(np.isin(labels, big_enough), labels, 0)
        regions_show=regions.max(axis=0)
        fig = plot_plate_carree(
            box, regions_show, transform=ccrs.PlateCarree(), patch_greenwich=False,
            cmap=my_cmap, vmin=1
        )
        fig.suptitle(title)
        fig.savefig(str(filename), bbox_inches='tight')
        return Path(filename)


def generate_scatter_plot(mask,sb,colourdata,sizedata,colourbarlabel,gamma,lower_threshold,upper_threshold,title,filename):

        ### obtain location of edges in space and time, the magnitude of the gradients and their abruptness
        ## arrays with data from the points with edges (mask==1)
        idx    = np.where(mask)
        sizdata  = sizedata[idx[0], idx[1], idx[2]]
        coldata  = colourdata[idx[0], idx[1], idx[2]]
        sobel  = sb[:, idx[0], idx[1], idx[2]]
        sgrad = np.sqrt(sobel[1]**2 + sobel[2]**2) / gamma
        sgrad = sgrad/sobel[3]*1000    # scale to 1000 km
        tgrad = sobel[0]/sobel[3]*10      # scale to 10 years

        #### sort the input in order to show most abrupt ones on top of the others in scatter plot
        inds = np.argsort(coldata)

        ######## plot
        import matplotlib
        my_cmap = matplotlib.cm.get_cmap('rainbow')
        my_cmap.set_under('w')
        fig = plt.figure()
        ax=plt.subplot(111)
        matplotlib.rc('xtick', labelsize=16)
        matplotlib.rc('ytick', labelsize=16)

        #### ellipses showing the threshold values of hysteresis thresholding
        dp = np.linspace(-np.pi/2, np.pi/2, 100)
        dt = upper_threshold * np.sin(dp) * 10
        dx = upper_threshold * np.cos(dp) / gamma * 1000

        # ellipse showing the aspect ratio. for scaling_factor=1 would be a circle
        # the radius of that circle is the upper threshold
        plt.plot(dx, dt, c='k')

        ## ellipse based on the lower threshold:
        dt = lower_threshold * np.sin(dp) * 10
        dx = lower_threshold * np.cos(dp) / gamma * 1000
        plt.plot(dx, dt, c='k')

        #data
        plt.scatter(sgrad[inds], tgrad[inds],s=sizdata[inds]**2,c=coldata[inds], marker = 'o', cmap =my_cmap );
        cbar=plt.colorbar()
        cbar.set_label(colourbarlabel)
        matplotlib.rcParams.update({'font.size': 16})
        ax.set_xlabel('spatial gradient in units / 1000 km')
        ax.set_ylabel('temporal gradient in units / decade')

        #### set axis ranges
        border=0.05
        Smin=np.min(sgrad)-(np.max(sgrad)-np.min(sgrad))*border
        Smax=np.max(sgrad)+(np.max(sgrad)-np.min(sgrad))*border
        Tmin=np.min(tgrad)-(np.max(tgrad)-np.min(tgrad))*border
        Tmax=np.max(tgrad)+(np.max(tgrad)-np.min(tgrad))*border

        ax.set_xlim(Smin, Smax)
        ax.set_ylim(Tmin, Tmax)

        #fig.suptitle(title)
        fig.savefig(str(filename), bbox_inches='tight')
        return Path(filename)


def compute_years_maxabrupt(box, mask, abruptness_3d, abruptness):
    idx=np.where(mask)
    indices=np.asarray(idx)
    mask_max=mask*0
    shapeidx=np.shape(idx)
    nofresults=shapeidx[1]
    for result in range(nofresults):
        [dim0,dim1,dim2]=indices[:,result]
        if (abruptness_3d[dim0, dim1, dim2] == abruptness[dim1,dim2]) and abruptness[dim1,dim2] > 0:
            mask_max[dim0, dim1, dim2] = 1
    years = np.array([dd.year for dd in box.dates])
    years_maxabrupt=(years[:,None,None]*mask_max).sum(axis=0)
    return years_maxabrupt


def generate_year_plot(box, years_maxabrupt, title, filename):
    import matplotlib
    my_cmap = matplotlib.cm.get_cmap('rainbow')
    my_cmap.set_under('w')
    maxval = np.max(years_maxabrupt)
    minval = np.min(years_maxabrupt[np.nonzero(years_maxabrupt)])
    fig = plot_plate_carree(
        box, years_maxabrupt, transform=ccrs.PlateCarree(), patch_greenwich=False,
        cmap=my_cmap, vmin=minval, vmax=maxval
    )
    fig.suptitle(title, fontsize=20)
    fig.savefig(str(filename), bbox_inches='tight')
    return Path(filename)


def generate_event_count_timeseries_plot(box, mask, title, filename):
    fig = plt.figure()
    ax=plt.subplot(111)
    ax.plot(box.dates, mask.sum(axis=1).sum(axis=1))
    ax.set_title(title, fontsize=20)
    ax.set_xlabel('year', fontsize=20)
    ax.set_ylabel('events', fontsize=20)
    fig.savefig(str(filename), bbox_inches='tight')
    return Path(filename)

# @noodles.schedule(call_by_ref=['data_set', 'canny_edges'])
# @noodles.maybe
# def make_report(config, data_set, calibration, canny_edges):
#     output_path  = Path(config.output_folder)
#
#     gamma = get_calibration_factor(config, calibration)
#     years = np.array([dd.year for dd in data_set.box.dates])
#     #years_timeseries_out = write_ts(years, output_path / "years_timeseries.txt")
#
#     mask=canny_edges['edges']
#     event_count=mask.sum(axis=0)
#
#     lower_threshold, upper_threshold = get_thresholds(config, calibration)
#     years3d=years[:,None,None]*mask
#     lats=data_set.box.lat
#     lats3d=lats[None,:,None]*mask
#     lons=data_set.box.lon
#     lons3d=lons[None,None,:]*mask
#
#     maxTgrad      = compute_maxTgrad(canny_edges)
#
#     ## abruptness
#     measures      = compute_measure15j(mask, years, data_set.data, 2, 30, 15)
#     abruptness_3d = measures['measure15j_3d']
#     abruptness    = measures['measure15j']
#
#     years_maxabrupt = compute_years_maxabrupt(data_set.box, mask, abruptness_3d, abruptness)
#
#     event_count_timeseries = mask.sum(axis=1).sum(axis=1)
#
#     signal_plot  = generate_signal_plot(
#         config, calibration, data_set.box, canny_edges['sobel'], "signal",
#         output_path / "signal.png")
#     region_plot  = generate_region_plot(
#         data_set.box, canny_edges['edges'], "regions",
#         output_path / "regions.png")
#     event_count_timeseries_plot = generate_event_count_timeseries_plot(
#         data_set.box, canny_edges['edges'], "event count",
#         output_path / "event_count_timeseries.png")
#     event_count_plot = generate_standard_map_plot(
#         data_set.box, event_count, "event count",
#         output_path / "event_count.png")
#
#     abruptness_plot  = generate_standard_map_plot(
#         data_set.box, abruptness,
#         "abruptness", output_path / "abruptness.png")
#     maxTgrad_plot    = generate_standard_map_plot(
#         data_set.box, maxTgrad,
#         "max. time gradient", output_path / "maxTgrad.png")
#     timeseries_plot = generate_timeseries_plot(
#         config, data_set.box, data_set.data, abruptness, abruptness_3d, "data at grid cell with largest abruptness",
#         output_path / "timeseries.png")
#
#     year_plot    = generate_year_plot(
#         data_set.box, years_maxabrupt, "year of largest abruptness",
#         output_path / "years_maxabrupt.png")
#     scatter_plot_abrupt=generate_scatter_plot(
#         mask,canny_edges['sobel'],abruptness_3d,abruptness_3d,"abruptness",gamma,lower_threshold,
#         upper_threshold,"space versus time gradients", output_path / "scatter_abruptness.png")
#     scatter_plot_years=generate_scatter_plot(
#         mask,canny_edges['sobel'],years3d,abruptness_3d,"year",gamma,lower_threshold,
#         upper_threshold,"space versus time gradients",output_path / "scatter_year.png")
#     scatter_plot_lats=generate_scatter_plot(
#         mask,canny_edges['sobel'],lats3d,abruptness_3d,"latitude",gamma,lower_threshold,
#         upper_threshold,"space versus time gradients",output_path / "scatter_latitude.png")
#     scatter_plot_lons=generate_scatter_plot(
#         mask,canny_edges['sobel'],lons3d,abruptness_3d,"longitude",gamma,lower_threshold,
#         upper_threshold,"space versus time gradients",output_path / "scatter_longitude.png")
#
#     maxTgrad_out             = write_netcdf_2d(maxTgrad, output_path / "maxTgrad.nc")
#
#     abruptness_out      = write_netcdf_2d(abruptness, output_path / "abruptness.nc")
#
#     years_maxabrupt_out = write_netcdf_2d(years_maxabrupt, output_path / "years_maxabrupt.nc")
#     event_count_out          = write_netcdf_2d(event_count, output_path / "event_count.nc")
#     event_count_timeseries_out = write_ts(event_count_timeseries, output_path / "event_count_timeseries.txt")
#
#     edge_mask_out      = write_netcdf_3d(mask, output_path / "edge_mask_detected.nc")
#
#     return noodles.lift({
#         'calibration': calibration,
#         'statistics': {
#             'max_maxTgrad': maxTgrad.max(),
#
#             'max_abruptness': abruptness.max()
#         },
#         'signal_plot': signal_plot,
#         'region_plot': region_plot,
#         'maxTgrad_out': maxTgrad_out,
#
#         'year_plot': year_plot,
#         'event_count_plot': event_count_plot,
#         'event_count_timeseries_plot': event_count_timeseries_plot,
#         'maxTgrad_plot': maxTgrad_plot,
#
#         'abruptness_plot': abruptness_plot,
#         'timeseries_plot': timeseries_plot,
#         'scatter_plot_abrupt': scatter_plot_abrupt,
#         'scatter_plot_years': scatter_plot_years,
#         'scatter_plot_lats': scatter_plot_lats,
#         'scatter_plot_lons': scatter_plot_lons,
#         'abruptness_out': abruptness_out,
#         'years_maxabrupt_out': years_maxabrupt_out,
#
#         'event_count_out': event_count_out,
#         'event_count_timeseries_out': event_count_timeseries_out,
#         'edge_mask_out': edge_mask_out
#     })


def make_report(config, data_set, calibration, canny_edges):
    output_path  = Path(config.output_folder)

    gamma = get_calibration_factor(config, calibration)
    years = np.array([dd.year for dd in data_set.box.dates])
    #years_timeseries_out = write_ts(years, output_path / "years_timeseries.txt")

    mask=canny_edges['edges']
    event_count=mask.sum(axis=0)

    lower_threshold, upper_threshold = get_thresholds(config, calibration)
    years3d=years[:,None,None]*mask
    lats=data_set.box.lat
    lats3d=lats[None,:,None]*mask
    lons=data_set.box.lon
    lons3d=lons[None,None,:]*mask

    maxTgrad      = compute_maxTgrad(canny_edges)

    ## abruptness
    measures      = compute_measure15j(mask, years, data_set.data, 2, 30, 15)
    abruptness_3d = measures['measure15j_3d']
    abruptness    = measures['measure15j']

    # dont save if max. abruptness is below 2
    if np.max(abruptness ) < 2:
        return None

    years_maxabrupt = compute_years_maxabrupt(data_set.box, mask, abruptness_3d, abruptness)

    # event_count_timeseries = mask.sum(axis=1).sum(axis=1)
    mask_plot  = generate_standard_map_plot(
        data_set.box, np.sum(mask, axis=0),
        "mask", output_path / "mask.png")
    signal_plot  = generate_signal_plot(
        config, calibration, data_set.box, canny_edges['sobel'], "signal",
        output_path / "signal.png")
    region_plot  = generate_region_plot(
        data_set.box, canny_edges['edges'], "regions",
        output_path / "regions.png")
    event_count_timeseries_plot = generate_event_count_timeseries_plot(
        data_set.box, canny_edges['edges'], "event count",
        output_path / "event_count_timeseries.png")
    event_count_plot = generate_standard_map_plot(
        data_set.box, event_count, "event count",
        output_path / "event_count.png")
    abruptness_plot  = generate_standard_map_plot(
        data_set.box, abruptness,
        "abruptness", output_path / "abruptness.png")
    maxTgrad_plot    = generate_standard_map_plot(
        data_set.box, maxTgrad,
        "max. time gradient", output_path / "maxTgrad.png")
    timeseries_plot = generate_timeseries_plot(
        config, data_set.box, data_set.data, abruptness, abruptness_3d, "data at grid cell with largest abruptness",
        output_path / "timeseries.png")

    year_plot = generate_year_plot(
        data_set.box, years_maxabrupt, "year of largest abruptness",
        output_path / "years_maxabrupt.png")
    # scatter_plot_abrupt=generate_scatter_plot(
    #     mask,canny_edges['sobel'],abruptness_3d,abruptness_3d,"abruptness",gamma,lower_threshold,
    #     upper_threshold,"space versus time gradients", output_path / "scatter_abruptness.png")
    # scatter_plot_years=generate_scatter_plot(
    #     mask,canny_edges['sobel'],years3d,abruptness_3d,"year",gamma,lower_threshold,
    #     upper_threshold,"space versus time gradients",output_path / "scatter_year.png")
    # scatter_plot_lats=generate_scatter_plot(
    #     mask,canny_edges['sobel'],lats3d,abruptness_3d,"latitude",gamma,lower_threshold,
    #     upper_threshold,"space versus time gradients",output_path / "scatter_latitude.png")
    # scatter_plot_lons=generate_scatter_plot(
    #     mask,canny_edges['sobel'],lons3d,abruptness_3d,"longitude",gamma,lower_threshold,
    #     upper_threshold,"space versus time gradients",output_path / "scatter_longitude.png")

    # event_count_timeseries_out = write_ts(event_count_timeseries, output_path / "event_count_timeseries.txt")

    # Save all maps to a single file
    image1 = plt.imread(os.path.join(output_path, "event_count.png"))
    image2 = plt.imread(os.path.join(output_path, "years_maxabrupt.png"))
    image3 = plt.imread(os.path.join(output_path, "abruptness.png"))
    image4 = plt.imread(os.path.join(output_path, "maxTgrad.png"))
    width = 2900
    height = 1800
    dpi = 100
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(int(width/dpi), int(height/dpi)))
    ax1.imshow(image1)
    ax1.axis("off")
    ax2.imshow(image2)
    ax2.axis("off")
    ax3.imshow(image3)
    ax3.axis("off")
    ax4.imshow(image4)
    ax4.axis("off")
    plt.savefig(os.path.join(output_path, "map_plots.png"), bbox_inches="tight")

    # Save all time series plots to a single file
    image1 = plt.imread(os.path.join(output_path, "timeseries.png"))
    image2 = plt.imread(os.path.join(output_path, "signal.png"))
    image3 = plt.imread(os.path.join(output_path, "event_count_timeseries.png"))
    width = 625
    height = 1475
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(int(width/dpi), int(height/dpi)))
    ax1.imshow(image1)
    ax1.axis("off")
    ax2.imshow(image2)
    ax2.axis("off")
    ax3.imshow(image3)
    ax3.axis("off")
    plt.savefig(os.path.join(output_path, "timeseries_plots.png"), bbox_inches="tight")

    return {
        'calibration': calibration,
        'statistics': {
            'max_maxTgrad': maxTgrad.max(),

            'max_abruptness': abruptness.max()
        },
        'signal_plot': signal_plot,
        'region_plot': region_plot,

        'event_count_plot': event_count_plot,
        'event_count_timeseries_plot': event_count_timeseries_plot,
        'maxTgrad_plot': maxTgrad_plot,

        'abruptness_plot': abruptness_plot,
        'timeseries_plot': timeseries_plot,

        'year_plot': year_plot,
    }

def generate_report(config):
    output_path = Path(config.output_folder)
    output_path.mkdir(parents=True, exist_ok=True)
    data_set = open_data_files(config)
    control_set = open_pi_control(config)
    if config.annual:
        data_set = annual_mean(data_set)
        control_set = annual_mean(control_set)
    else:
        data_set = select_month(config, data_set)
        control_set = select_month(config, control_set)
    calibration = compute_calibration(config, control_set)
    canny_edges = compute_canny_edges(config, data_set, calibration)
    return make_report(config, data_set, calibration, canny_edges)
