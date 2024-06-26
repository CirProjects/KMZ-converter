from flask import Flask, request, send_file, render_template, redirect, url_for
import os
import zipfile
from osgeo import ogr, osr, gdalconst
import tempfile

app = Flask(__name__)
os.makedirs('uploads', exist_ok=True)
 
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return redirect(request.url)

    file = request.files['file']
    if file.filename == '':
        return redirect(request.url)

    if file and file.filename.endswith('.kmz'):
        with tempfile.NamedTemporaryFile(suffix='.kmz', delete=False) as temp_kmz_file:
            temp_file_path = temp_kmz_file.name
            file.save(temp_file_path)

            zip_path = kmz_converter(temp_file_path)

            try:
                os.remove(temp_file_path)  # Remove the temporary KMZ file
            except OSError as e:
                print(f"Error deleting temporary file: {e}")

            if zip_path and os.path.exists(zip_path):
                try:
                    return send_file(zip_path, as_attachment=True)
                finally:
                    try:
                        os.remove(zip_path)  # Remove the temporary ZIP output file
                    except OSError as e:
                        print(f"Error deleting temporary output file: {e}")

    return redirect(request.url)

def kmz_converter(kmz_file):
    data_source = open_kmz(kmz_file)
    points_shp_name = set_output_filename(kmz_file, 'points')
    lines_shp_name = set_output_filename(kmz_file, 'lines')
    polygons_shp_name = set_output_filename(kmz_file, 'polygons')

    points_datastore = create_output_datastore(points_shp_name)
    points_layer = create_output_layer(points_datastore, ogr.wkbMultiPoint)
    add_fields(points_layer)

    lines_datastore = create_output_datastore(lines_shp_name)
    lines_layer = create_output_layer(lines_datastore, ogr.wkbMultiLineString)
    add_fields(lines_layer)

    polygons_datastore = create_output_datastore(polygons_shp_name)
    polygons_layer = create_output_layer(polygons_datastore, ogr.wkbMultiPolygon)
    add_fields(polygons_layer)

    feature_counter = 0
    points_counter = 0
    lines_counter = 0
    polygons_counter = 0

    layer_count = data_source.GetLayerCount()
    for i in range(layer_count):
        layer = data_source.GetLayer(i)
        for feature in layer:
            feature_counter += 1
            geom = feature.GetGeometryRef()
            geom_type = geom.GetGeometryName()
            field_names = ['Name', 'description', 'icon', 'snippet']

            if geom_type in ('POINT', 'MULTIPOINT'):
                points_counter += 1
                layer_defn = points_layer.GetLayerDefn()
                out_feature = ogr.Feature(layer_defn)
                out_geom = ogr.ForceToMultiPoint(geom)

            elif geom_type in ('LINESTRING', 'MULTILINESTRING'):
                lines_counter += 1
                layer_defn = lines_layer.GetLayerDefn()
                out_feature = ogr.Feature(layer_defn)
                out_geom = ogr.ForceToMultiLineString(geom)

            elif geom_type in ('POLYGON', 'MULTIPOLYGON'):
                polygons_counter += 1
                layer_defn = polygons_layer.GetLayerDefn()
                out_feature = ogr.Feature(layer_defn)
                out_geom = ogr.ForceToMultiPolygon(geom)

            else:
                continue

            out_geom.FlattenTo2D()
            out_feature.SetGeometry(out_geom)

            for field_name in field_names:
                try:
                    out_feature.SetField(field_name, feature.GetField(field_name))
                except:
                    pass

            out_feature.SetField('layer_name', layer.GetName())
            out_feature.SetField('id', feature_counter)

            if geom_type in ('POINT', 'MULTIPOINT'):
                points_layer.CreateFeature(out_feature)
            elif geom_type in ('LINESTRING', 'MULTILINESTRING'):
                lines_layer.CreateFeature(out_feature)
            elif geom_type in ('POLYGON', 'MULTIPOLYGON'):
                polygons_layer.CreateFeature(out_feature)

            out_feature = None

        layer.ResetReading()

    points_datastore = None
    points_layer = None
    lines_datastore = None
    lines_layer = None
    polygons_datastore = None
    polygons_layer = None

    zip_filename = os.path.join(os.path.dirname(kmz_file), 'output.zip')
    zip_shapefiles(points_shp_name, lines_shp_name, polygons_shp_name, zip_filename)
    clean_up_shapefiles(points_shp_name, lines_shp_name, polygons_shp_name)

    return zip_filename

def open_kmz(kmz_file):
    driver = ogr.GetDriverByName('LIBKML')
    data_source = driver.Open(kmz_file, gdalconst.GA_ReadOnly)
    if data_source is None:
        print("Failed to open file.")
        exit()
    return data_source

def set_output_filename(input_filename, geom_type):
    dir_name, filename = os.path.split(input_filename)
    output_filename = os.path.splitext(filename)[0] + '_' + geom_type + '.shp'
    return os.path.join(os.path.dirname(input_filename), output_filename)

def create_output_datastore(shp_name):
    driver = ogr.GetDriverByName('ESRI Shapefile')
    if os.path.exists(shp_name):
        os.remove(shp_name)
    try:
        output_datastore = driver.CreateDataSource(shp_name)
    except:
        print("Could not create shapefile %s." % shp_name)
    return output_datastore

def create_output_layer(datastore, geom_type):
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    new_pts_layer = datastore.CreateLayer('layer1', srs, geom_type)
    if new_pts_layer is None:
        print('Error creating layer.')
        sys.exit(1)
    return new_pts_layer

def add_fields(layer):
    fields = {
        'Name': 50,
        'description': 128,
        'icon': 10,
        'snippet': 128,
        'layer_name': 50
    }
    field = ogr.FieldDefn('id', ogr.OFTInteger)
    layer.CreateField(field)
    for field_name, field_length in fields.items():
        field = ogr.FieldDefn(field_name, ogr.OFTString)
        field.SetWidth(field_length)
        layer.CreateField(field)

def zip_shapefiles(points_shp_name, lines_shp_name, polygons_shp_name, zip_filename):
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for shp_name in [points_shp_name, lines_shp_name, polygons_shp_name]:
            shp_dir, shp_file = os.path.split(shp_name)
            for ext in ['.shp', '.shx', '.dbf', '.prj']:
                file_path = os.path.join(shp_dir, shp_file.replace('.shp', ext))
                if os.path.exists(file_path):
                    zipf.write(file_path, os.path.basename(file_path))

    return zip_filename

def clean_up_shapefiles(points_shp_name, lines_shp_name, polygons_shp_name):
    for shp_name in [points_shp_name, lines_shp_name, polygons_shp_name]:
        shp_dir, shp_file = os.path.split(shp_name)
        for ext in ['.shp', '.shx', '.dbf', '.prj']:
            file_path = os.path.join(shp_dir, shp_file.replace('.shp', ext))
            if os.path.exists(file_path):
                os.remove(file_path)

if __name__ == '__main__':
    app.run(debug=True)
