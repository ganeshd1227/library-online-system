"""
Forms for authentication, account management, and the OTP-based
password-reset flow.
"""
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

User = get_user_model()


class LoginForm(forms.Form):
    identifier = forms.CharField(
        label="Email / Library Card ID / Phone Number",
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Enter email, card ID or phone', 'autofocus': True})
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'placeholder': 'Enter your password'})
    )


class BaseStaffForm(forms.ModelForm):
    """Shared logic for creating/editing Librarian and User accounts."""
    password = forms.CharField(
        label="Password", required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'placeholder': 'Leave blank to keep current password'}),
        help_text="Leave blank when editing to keep the existing password.",
    )

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password:
            validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk and not cleaned.get('password'):
            self.add_error('password', "Password is required for new accounts.")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        password = self.cleaned_data.get('password')
        if password:
            instance.set_password(password)
        if commit:
            instance.save()
        return instance


class LibrarianForm(BaseStaffForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone_number', 'employee_id', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input'}),
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-input'}),
            'employee_id': forms.TextInput(attrs={'class': 'form-input'}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.role = User.Role.LIBRARIAN
        if not instance.username:
            instance.username = instance.email
        if commit:
            instance.save()
        return instance


class LibraryUserForm(BaseStaffForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone_number', 'library_card_id', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input'}),
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-input'}),
            'library_card_id': forms.TextInput(attrs={'class': 'form-input'}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.role = User.Role.USER
        if not instance.username:
            instance.username = instance.library_card_id or instance.email
        if commit:
            instance.save()
        return instance


class UserSelfPasswordChangeForm(forms.Form):
    """Users can ONLY change their password — never email/phone/card ID/role."""
    current_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-input'}))
    new_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-input'}))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-input'}))

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        pwd = self.cleaned_data['current_password']
        if not self.user.check_password(pwd):
            raise ValidationError("Your current password is incorrect.")
        return pwd

    def clean_new_password(self):
        pwd = self.cleaned_data['new_password']
        validate_password(pwd, user=self.user)
        return pwd

    def clean(self):
        cleaned = super().clean()
        new = cleaned.get('new_password')
        confirm = cleaned.get('confirm_password')
        if new and confirm and new != confirm:
            raise ValidationError("New password and confirmation do not match.")
        return cleaned


# ---------------------------------------------------------------
# OTP-BASED PASSWORD RESET FORMS
# ---------------------------------------------------------------
class ForgotPasswordForm(forms.Form):
    """Step 1: the user enters their registered email to request an OTP."""
    email = forms.EmailField(
        label="Email Address",
        widget=forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'you@example.com', 'autofocus': True}),
    )


class VerifyOTPForm(forms.Form):
    """Step 2: the user enters the code they received by email."""
    otp_code = forms.CharField(
        label="Verification Code",
        min_length=4, max_length=8,
        widget=forms.TextInput(attrs={
            'class': 'form-input otp-input', 'placeholder': '------',
            'inputmode': 'numeric', 'autocomplete': 'one-time-code', 'autofocus': True,
        }),
    )


class SetNewPasswordForm(forms.Form):
    """Step 3: the user chooses a new password after a verified OTP."""
    new_password = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'autofocus': True}),
    )
    confirm_password = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={'class': 'form-input'}),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_new_password(self):
        pwd = self.cleaned_data['new_password']
        validate_password(pwd, user=self.user)
        return pwd

    def clean(self):
        cleaned = super().clean()
        new = cleaned.get('new_password')
        confirm = cleaned.get('confirm_password')
        if new and confirm and new != confirm:
            raise ValidationError("New password and confirmation do not match.")
        return cleaned
