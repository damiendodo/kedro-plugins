import importlib
from pathlib import Path, PurePosixPath

import geopandas as gpd
import pytest
from fsspec.implementations.http import HTTPFileSystem
from fsspec.implementations.local import LocalFileSystem
from gcsfs import GCSFileSystem
from kedro.io.core import PROTOCOL_DELIMITER, Version, generate_timestamp
from pandas.testing import assert_frame_equal
from s3fs import S3FileSystem
from shapely.geometry import Point

from kedro_datasets import KedroDeprecationWarning
from kedro_datasets._io import DatasetError
from kedro_datasets.geopandas import GeoJSONDataset
from kedro_datasets.geopandas.geojson_dataset import _DEPRECATED_CLASSES


@pytest.fixture(params=[None])
def load_version(request):
    return request.param


@pytest.fixture(params=[None])
def save_version(request):
    return request.param or generate_timestamp()


@pytest.fixture
def filepath(tmp_path):
    return (tmp_path / "test.geojson").as_posix()


@pytest.fixture(params=[None])
def load_args(request):
    return request.param


@pytest.fixture(params=[{"driver": "GeoJSON"}])
def save_args(request):
    return request.param


@pytest.fixture
def dummy_dataframe():
    return gpd.GeoDataFrame(
        {"col1": [1, 2], "col2": [4, 5], "col3": [5, 6]},
        geometry=[Point(1, 1), Point(2, 2)],
    )


@pytest.fixture
def geojson_dataset(filepath, load_args, save_args, fs_args):
    return GeoJSONDataset(
        filepath=filepath, load_args=load_args, save_args=save_args, fs_args=fs_args
    )


@pytest.fixture
def versioned_geojson_dataset(filepath, load_version, save_version):
    return GeoJSONDataset(
        filepath=filepath, version=Version(load_version, save_version)
    )


@pytest.mark.parametrize(
    "module_name",
    ["kedro_datasets.geopandas", "kedro_datasets.geopandas.geojson_dataset"],
)
@pytest.mark.parametrize("class_name", _DEPRECATED_CLASSES)
def test_deprecation(module_name, class_name):
    with pytest.warns(
        KedroDeprecationWarning, match=f"{repr(class_name)} has been renamed"
    ):
        getattr(importlib.import_module(module_name), class_name)


class TestGeoJSONDataset:
    def test_save_and_load(self, geojson_dataset, dummy_dataframe):
        """Test that saved and reloaded data matches the original one."""
        geojson_dataset.save(dummy_dataframe)
        reloaded_df = geojson_dataset.load()
        assert_frame_equal(reloaded_df, dummy_dataframe)
        assert geojson_dataset._fs_open_args_load == {}
        assert geojson_dataset._fs_open_args_save == {"mode": "wb"}

    @pytest.mark.parametrize("geojson_dataset", [{"index": False}], indirect=True)
    def test_load_missing_file(self, geojson_dataset):
        """Check the error while trying to load from missing source."""
        pattern = r"Failed while loading data from data set GeoJSONDataset"
        with pytest.raises(DatasetError, match=pattern):
            geojson_dataset.load()

    def test_exists(self, geojson_dataset, dummy_dataframe):
        """Test `exists` method invocation for both cases."""
        assert not geojson_dataset.exists()
        geojson_dataset.save(dummy_dataframe)
        assert geojson_dataset.exists()

    @pytest.mark.parametrize(
        "load_args", [{"crs": "init:4326"}, {"crs": "init:2154", "driver": "GeoJSON"}]
    )
    def test_load_extra_params(self, geojson_dataset, load_args):
        """Test overriding default save args"""
        for k, v in load_args.items():
            assert geojson_dataset._load_args[k] == v

    @pytest.mark.parametrize(
        "save_args", [{"driver": "ESRI Shapefile"}, {"driver": "GPKG"}]
    )
    def test_save_extra_params(self, geojson_dataset, save_args):
        """Test overriding default save args"""
        for k, v in save_args.items():
            assert geojson_dataset._save_args[k] == v

    @pytest.mark.parametrize(
        "fs_args",
        [{"open_args_load": {"mode": "rb", "compression": "gzip"}}],
        indirect=True,
    )
    def test_open_extra_args(self, geojson_dataset, fs_args):
        assert geojson_dataset._fs_open_args_load == fs_args["open_args_load"]
        assert geojson_dataset._fs_open_args_save == {"mode": "wb"}

    @pytest.mark.parametrize(
        "path,instance_type",
        [
            ("s3://bucket/file.geojson", S3FileSystem),
            ("/tmp/test.geojson", LocalFileSystem),
            ("gcs://bucket/file.geojson", GCSFileSystem),
            ("file:///tmp/file.geojson", LocalFileSystem),
            ("https://example.com/file.geojson", HTTPFileSystem),
        ],
    )
    def test_protocol_usage(self, path, instance_type):
        geojson_dataset = GeoJSONDataset(filepath=path)
        assert isinstance(geojson_dataset._fs, instance_type)

        path = path.split(PROTOCOL_DELIMITER, 1)[-1]

        assert str(geojson_dataset._filepath) == path
        assert isinstance(geojson_dataset._filepath, PurePosixPath)

    def test_catalog_release(self, mocker):
        fs_mock = mocker.patch("fsspec.filesystem").return_value
        filepath = "test.geojson"
        geojson_dataset = GeoJSONDataset(filepath=filepath)
        geojson_dataset.release()
        fs_mock.invalidate_cache.assert_called_once_with(filepath)


class TestGeoJSONDatasetVersioned:
    def test_version_str_repr(self, load_version, save_version):
        """Test that version is in string representation of the class instance
        when applicable."""
        filepath = "test.geojson"
        ds = GeoJSONDataset(filepath=filepath)
        ds_versioned = GeoJSONDataset(
            filepath=filepath, version=Version(load_version, save_version)
        )
        assert filepath in str(ds)
        assert "version" not in str(ds)

        assert filepath in str(ds_versioned)
        ver_str = f"version=Version(load={load_version}, save='{save_version}')"
        assert ver_str in str(ds_versioned)
        assert "GeoJSONDataset" in str(ds_versioned)
        assert "GeoJSONDataset" in str(ds)
        assert "protocol" in str(ds_versioned)
        assert "protocol" in str(ds)

    def test_save_and_load(self, versioned_geojson_dataset, dummy_dataframe):
        """Test that saved and reloaded data matches the original one for
        the versioned data set."""
        versioned_geojson_dataset.save(dummy_dataframe)
        reloaded_df = versioned_geojson_dataset.load()
        assert_frame_equal(reloaded_df, dummy_dataframe)

    def test_no_versions(self, versioned_geojson_dataset):
        """Check the error if no versions are available for load."""
        pattern = r"Did not find any versions for GeoJSONDataset\(.+\)"
        with pytest.raises(DatasetError, match=pattern):
            versioned_geojson_dataset.load()

    def test_exists(self, versioned_geojson_dataset, dummy_dataframe):
        """Test `exists` method invocation for versioned data set."""
        assert not versioned_geojson_dataset.exists()
        versioned_geojson_dataset.save(dummy_dataframe)
        assert versioned_geojson_dataset.exists()

    def test_prevent_override(self, versioned_geojson_dataset, dummy_dataframe):
        """Check the error when attempt to override the same data set
        version."""
        versioned_geojson_dataset.save(dummy_dataframe)
        pattern = (
            r"Save path \'.+\' for GeoJSONDataset\(.+\) must not "
            r"exist if versioning is enabled"
        )
        with pytest.raises(DatasetError, match=pattern):
            versioned_geojson_dataset.save(dummy_dataframe)

    @pytest.mark.parametrize(
        "load_version", ["2019-01-01T23.59.59.999Z"], indirect=True
    )
    @pytest.mark.parametrize(
        "save_version", ["2019-01-02T00.00.00.000Z"], indirect=True
    )
    def test_save_version_warning(
        self, versioned_geojson_dataset, load_version, save_version, dummy_dataframe
    ):
        """Check the warning when saving to the path that differs from
        the subsequent load path."""
        pattern = (
            rf"Save version '{save_version}' did not match load version "
            rf"'{load_version}' for GeoJSONDataset\(.+\)"
        )
        with pytest.warns(UserWarning, match=pattern):
            versioned_geojson_dataset.save(dummy_dataframe)

    def test_http_filesystem_no_versioning(self):
        pattern = "Versioning is not supported for HTTP protocols."

        with pytest.raises(DatasetError, match=pattern):
            GeoJSONDataset(
                filepath="https://example/file.geojson", version=Version(None, None)
            )

    def test_versioning_existing_dataset(
        self, geojson_dataset, versioned_geojson_dataset, dummy_dataframe
    ):
        """Check the error when attempting to save a versioned dataset on top of an
        already existing (non-versioned) dataset."""
        geojson_dataset.save(dummy_dataframe)
        assert geojson_dataset.exists()
        assert geojson_dataset._filepath == versioned_geojson_dataset._filepath
        pattern = (
            f"(?=.*file with the same name already exists in the directory)"
            f"(?=.*{versioned_geojson_dataset._filepath.parent.as_posix()})"
        )
        with pytest.raises(DatasetError, match=pattern):
            versioned_geojson_dataset.save(dummy_dataframe)

        # Remove non-versioned dataset and try again
        Path(geojson_dataset._filepath.as_posix()).unlink()
        versioned_geojson_dataset.save(dummy_dataframe)
        assert versioned_geojson_dataset.exists()
