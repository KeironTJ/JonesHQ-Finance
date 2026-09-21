def test_csrf_error_template_compiles(app):
    template = app.jinja_env.get_template('errors/csrf.html')

    assert template is not None