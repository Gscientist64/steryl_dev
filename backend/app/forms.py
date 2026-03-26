# STERYL_UP/app/forms.py

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, BooleanField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError
from .models import User

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    remember = BooleanField('Remember Me')

class RegisterForm(FlaskForm):
    first_name = StringField('First Name', validators=[DataRequired(), Length(min=2, max=120)])
    last_name = StringField('Last Name', validators=[DataRequired(), Length(min=2, max=120)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[
        DataRequired(), 
        Length(min=8, message='Password must be at least 8 characters')
    ])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(),
        EqualTo('password', message='Passwords must match')
    ])
    phone = StringField('Phone Number', validators=[Length(max=15)])
    country = StringField('Country', validators=[DataRequired()])
    account_type = SelectField('Account Type', choices=[
        ('hospital', 'Hospital'),
        ('lab', 'Lab'),
        ('research', 'Research'),
        ('supplier', 'Supplier'),
        ('professional', 'Professional'),
        ('student', 'Student')
    ], validators=[DataRequired()])
    terms = BooleanField('I agree to the terms and conditions', validators=[DataRequired()])

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('Email already registered. Please use a different email or login.')