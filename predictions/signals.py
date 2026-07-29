from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import Profile, TipLeg

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    Profile.objects.get_or_create(user=instance)


@receiver(post_save, sender=TipLeg)
def sync_tip_status(sender, instance, **kwargs):
    # TipLegAdmin (and the TipLegInline on TipAdmin) let staff edit a leg's
    # status directly. Without this, that edit never propagated to the
    # parent Tip - Tip.evaluate() existed and was covered by tests, but
    # nothing in the running app ever called it, so Tip.status could end
    # up disagreeing with the actual results of its legs.
    if instance.tip_id:
        instance.tip.evaluate()