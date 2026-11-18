using System;

namespace Antreklabs.Bayi.Altyapi;

/// <summary>
/// Testten önce arayüzden giriş yapılır (Java <c>@OturumAcik</c>). Yalnızca elle yazılmış referans
/// testler içindir; üretilen testler girişi case adımı olarak içerir (cs-araclar guard izin vermez).
/// </summary>
[AttributeUsage(AttributeTargets.Class, AllowMultiple = false, Inherited = true)]
public sealed class OturumAcikAttribute : Attribute
{
}
