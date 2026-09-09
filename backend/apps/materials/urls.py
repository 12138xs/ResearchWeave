from django.urls import path

from apps.materials.views import CardImport, MaterialDetail, MaterialList, VersionDetail, VersionFile, VersionRetry, VersionUpload

urlpatterns = [
    path("materials/", MaterialList.as_view()),
    path("materials/<int:pk>/", MaterialDetail.as_view()),
    path("materials/<int:pk>/versions/", VersionUpload.as_view()),
    path("materials/<int:pk>/versions/<int:version_id>/", VersionDetail.as_view()),
    path("materials/<int:pk>/versions/<int:version_id>/file/", VersionFile.as_view()),
    path("materials/<int:pk>/versions/<int:version_id>/retry/", VersionRetry.as_view()),
    path("materials/<int:pk>/versions/<int:version_id>/cards/", CardImport.as_view()),
]
