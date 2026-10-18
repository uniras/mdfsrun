pip3 install build twine
python3 -m build
twine upload --repository pypi dist/*
rm -rf dist
rm -rf *.egg-info
